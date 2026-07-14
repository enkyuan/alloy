"""Anthropic LLM provider.

Uses the official async Anthropic SDK. Translates the SDK's neutral tool payload
to Anthropic's ``input_schema`` format via ``to_anthropic``. Enable with
``KAJI_MODEL_PROVIDER=anthropic``.
"""

from __future__ import annotations

import json
import logging
from importlib import import_module
import math
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

from kaji.core.config import get_settings
from kaji.runtime.providers.base import (
    LinearStringParts,
    ModelProvider,
    ProviderResponseBudget,
    RawToolCallFragment,
    capture_provider_diagnostics,
)
from kaji.runtime.providers.errors import (
    ProviderConfigError,
    ProviderOutputLimitError,
    provider_error_from_exception,
)
from kaji.runtime.providers.costs import calculate_cost_usd, lookup_cost
from kaji.runtime.providers.registry import register_provider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelMetadata,
    ModelResponseChunk,
    ProviderResponseLimits,
    TokenMetrics,
)
from kaji.runtime.providers._cancellation import (
    raise_if_cancelled as _raise_if_cancelled,
)
from kaji.runtime.providers._translate import format_messages_anthropic
from kaji.runtime.tools.payload import to_anthropic

logger = logging.getLogger(__name__)


class AnthropicProvider(ModelProvider):
    """Anthropic Messages API provider with streaming and tool use."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        request_timeout_seconds: float | None = None,
        **_: Any,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        self.model_name = model if model is not None else settings.ANTHROPIC_MODEL
        if isinstance(request_timeout_seconds, bool) or (
            request_timeout_seconds is not None
            and not isinstance(request_timeout_seconds, (int, float))
        ):
            raise TypeError("request_timeout_seconds must be a positive finite number")
        if request_timeout_seconds is not None and (
            not math.isfinite(float(request_timeout_seconds))
            or request_timeout_seconds <= 0
        ):
            raise ValueError("request_timeout_seconds must be a positive finite number")
        self.request_timeout_seconds = (
            None if request_timeout_seconds is None else float(request_timeout_seconds)
        )
        self._client: Any = None

        if not self.api_key:
            raise ProviderConfigError(
                "Anthropic API key is not configured. Set ANTHROPIC_API_KEY."
            )

    @property
    def client(self) -> Any:
        """Lazily construct the async Anthropic client."""
        if self._client is None:
            try:
                AsyncAnthropic = import_module("anthropic").AsyncAnthropic
            except ImportError:
                raise ProviderConfigError(
                    "Anthropic provider requires anthropic. Install kaji-sdk[anthropic]."
                ) from None

            # Kaji does not own a cancellable pre-stream retry loop. Disable
            # opaque SDK backoff so caller cancellation cannot be trapped in it.
            client_options: Dict[str, Any] = {
                "api_key": self.api_key,
                "max_retries": 0,
            }
            if self.request_timeout_seconds is not None:
                client_options["timeout"] = self.request_timeout_seconds
            self._client = AsyncAnthropic(**client_options)
        return self._client

    def _split_messages(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """Return (system_prompt, anthropic_messages).

        Delegates to :func:`format_messages_anthropic` which correctly maps
        tool results to Anthropic ``tool_result`` content blocks rather than
        collapsing them to assistant text.
        """
        return format_messages_anthropic(messages, system_instruction)

    @staticmethod
    def _parse_tool_use(content_blocks: Any) -> tuple[str, List[Dict[str, Any]]]:
        """Extract text and tool_use blocks from the Anthropic response content."""
        text_parts: List[str] = []
        tool_calls: List[Dict[str, Any]] = []

        for block in content_blocks or []:
            block_type = (
                getattr(block, "type", None)
                if not isinstance(block, dict)
                else block.get("type")
            )
            if block_type == "text":
                text_parts.append(
                    getattr(block, "text", "")
                    if not isinstance(block, dict)
                    else block.get("text", "")
                )
            elif block_type == "tool_use":
                if isinstance(block, dict):
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "name": block.get("name"),
                            "arguments": block.get("input", {}),
                        }
                    )
                else:
                    tool_calls.append(
                        {
                            "id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                            "arguments": getattr(block, "input", {}),
                        }
                    )

        return "".join(text_parts), tool_calls

    @staticmethod
    def _parse_tool_args(raw: str, name: str, tool_id: Optional[str]) -> Dict[str, Any]:
        """Parse a streamed tool_use ``input_json`` payload.

        When the model's tool-arg JSON does not parse, we do two things:

        - log only the tool identity, payload length, and exception type,
        - return ``{"__parse_error": str(exc)}`` so the planner fails the
          call closed via the existing sentinel in ``planner.py``.

        The raw text is not copied into the event payload because events are
        persisted, replayed, and surfaced to UI, and the stream can contain
        whatever the model echoed back. ``str(exc)`` from ``JSONDecodeError``
        carries only line/column context, not a slice of the payload.
        """
        payload = raw or "{}"
        try:
            parsed = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "Anthropic streaming tool_use input failed to parse "
                "for tool=%s id=%s (arguments redacted; %d characters; %s)",
                name,
                tool_id or "<unknown>",
                len(raw),
                type(exc).__name__,
            )
            return {"__parse_error": str(exc)}
        if not isinstance(parsed, dict):
            return {"__parse_error": "tool arguments must decode to an object"}
        return parsed

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> GenerateResponse:
        system, anthropic_messages = self._split_messages(messages, system_instruction)

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = to_anthropic(tools)

        _raise_if_cancelled(cancellation_token)

        request_error = None
        try:
            response = await self.client.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Anthropic API request failed (%s; details redacted)",
                type(e).__name__,
            )
            request_error = provider_error_from_exception(
                service="anthropic", action="request", error=e
            )

        if request_error is not None:
            raise request_error from None

        text, tool_calls = self._parse_tool_use(response.content)
        accepted = ProviderResponseBudget(response_limits).accept_normalized(
            text, tool_calls
        )
        text = accepted.delta
        tool_calls = list(accepted.tool_calls)

        usage = getattr(response, "usage", None)
        metrics = TokenMetrics(
            prompt_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            total_tokens=(
                (getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0))
                if usage
                else 0
            ),
        )
        metadata = ModelMetadata(provider_name="anthropic", model_name=self.model_name)

        return GenerateResponse(
            text=text,
            tool_calls=cast(Any, tool_calls),
            metadata=metadata,
            metrics=metrics,
            cost_usd=(
                calculate_cost_usd(
                    self.model_name,
                    metrics.prompt_tokens,
                    metrics.completion_tokens,
                )
                if usage is not None and lookup_cost(self.model_name) is not None
                else None
            ),
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        system, anthropic_messages = self._split_messages(messages, system_instruction)

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = to_anthropic(tools)

        _raise_if_cancelled(cancellation_token)

        open_error = None
        try:
            stream = self.client.messages.stream(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Anthropic streaming API request failed (%s; details redacted)",
                type(e).__name__,
            )
            open_error = provider_error_from_exception(
                service="anthropic", action="stream", error=e
            )

        if open_error is not None:
            raise open_error from None

        # Accumulate tool_use blocks — Anthropic streams them in deltas that
        # must be reassembled before the arguments are valid JSON.
        pending_tool: Dict[str, Any] = {}
        next_tool_key = 0
        budget = ProviderResponseBudget(response_limits)
        latest_metrics: TokenMetrics | None = None

        iteration_error = None
        try:
            async with stream as s:
                async for event in s:
                    _raise_if_cancelled(cancellation_token)

                    event_type = getattr(event, "type", None)
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        prompt_tokens = getattr(
                            usage,
                            "input_tokens",
                            latest_metrics.prompt_tokens if latest_metrics else 0,
                        )
                        completion_tokens = getattr(
                            usage,
                            "output_tokens",
                            latest_metrics.completion_tokens if latest_metrics else 0,
                        )
                        latest_metrics = TokenMetrics(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            total_tokens=prompt_tokens + completion_tokens,
                        )

                    if event_type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            tool_id = str(getattr(block, "id", None) or "")
                            name = str(getattr(block, "name", None) or "")
                            tool_key = next_tool_key
                            next_tool_key += 1
                            budget.accept_raw(
                                tool_fragments=(
                                    RawToolCallFragment(
                                        key=tool_key,
                                        starts_call=True,
                                        id_fragment=tool_id,
                                        name_fragment=name,
                                    ),
                                )
                            )
                            pending_tool = {
                                "key": tool_key,
                                "id": tool_id,
                                "name": name,
                                "arguments": LinearStringParts(),
                            }

                    elif event_type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        delta_type = getattr(delta, "type", None)
                        if delta_type == "text_delta":
                            text = getattr(delta, "text", "")
                            if text:
                                budget.accept_raw(text=text)
                                yield ModelResponseChunk(delta=text)
                        elif delta_type == "input_json_delta":
                            fragment = getattr(delta, "partial_json", "")
                            if pending_tool and fragment:
                                budget.accept_raw(
                                    tool_fragments=(
                                        RawToolCallFragment(
                                            key=pending_tool["key"],
                                            arguments_fragment=fragment,
                                        ),
                                    )
                                )
                                pending_tool["arguments"].append(fragment)

                    elif event_type == "content_block_stop" and pending_tool:
                        raw_arguments = pending_tool["arguments"].join()
                        budget.record_tool_argument_join()
                        args = self._parse_tool_args(
                            raw=raw_arguments,
                            name=pending_tool.get("name") or "",
                            tool_id=pending_tool.get("id"),
                        )
                        yield ModelResponseChunk(
                            delta="",
                            tool_calls=cast(
                                Any,
                                [
                                    {
                                        "id": pending_tool.get("id"),
                                        "name": pending_tool.get("name"),
                                        "arguments": args,
                                    }
                                ],
                            ),
                        )
                        pending_tool = {}
        except ProviderOutputLimitError:
            raise
        except Exception as e:  # noqa: BLE001
            context: BaseException | None = e.__context__
            while context is not None:
                if isinstance(context, ProviderOutputLimitError):
                    raise context from None
                context = context.__context__
            logger.error(
                "Anthropic streaming API iteration failed (%s; details redacted)",
                type(e).__name__,
            )
            iteration_error = provider_error_from_exception(
                service="anthropic", action="stream", error=e
            )
        finally:
            capture_provider_diagnostics(budget.diagnostics)

        if iteration_error is not None:
            raise iteration_error from None

        if latest_metrics is not None:
            yield ModelResponseChunk(
                metrics=latest_metrics,
                cost_usd=(
                    calculate_cost_usd(
                        self.model_name,
                        latest_metrics.prompt_tokens,
                        latest_metrics.completion_tokens,
                    )
                    if lookup_cost(self.model_name) is not None
                    else None
                ),
            )


register_provider("anthropic", AnthropicProvider)
