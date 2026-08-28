"""OpenAI LLM provider.

Uses the official async OpenAI SDK (the same dependency the OpenAI TTS path
uses). Consumes the SDK's neutral tool payload and translates it to OpenAI's
function-tool format at this boundary via ``to_openai``. The safe default is
the mock provider; OpenAI is opt-in via ``KAJI_MODEL_PROVIDER=openai``.
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
    close_provider_stream,
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
from kaji.runtime.providers._translate import format_messages_openai
from kaji.runtime.tools.payload import to_openai

logger = logging.getLogger(__name__)


class OpenAIProvider(ModelProvider):
    """OpenAI chat-completions provider with streaming and tool calls."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        """Construct an OpenAI provider.

        Arguments take precedence over environment-derived settings. When an
        argument is None, the value is read from ``Settings`` (env / .env).
        This keeps explicit construction usable without depending on env.
        """
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY
        self.model_name = model if model is not None else settings.OPENAI_MODEL
        self.base_url = base_url if base_url is not None else settings.OPENAI_BASE_URL
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
                "OpenAI API key is not configured. Set OPENAI_API_KEY."
            )

    @property
    def client(self) -> Any:
        """Lazily construct the async OpenAI client."""
        if self._client is None:
            try:
                AsyncOpenAI = import_module("openai").AsyncOpenAI
            except ImportError:
                raise ProviderConfigError(
                    "OpenAI provider requires openai. Install kaji[openai]."
                ) from None

            # Kaji does not own a cancellable pre-stream retry loop. Disable
            # opaque SDK backoff so caller cancellation cannot be trapped in it.
            client_options: Dict[str, Any] = {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "max_retries": 0,
            }
            if self.request_timeout_seconds is not None:
                client_options["timeout"] = self.request_timeout_seconds
            self._client = AsyncOpenAI(
                **client_options,
            )
        return self._client

    def _build_messages(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str],
    ) -> List[Dict[str, Any]]:
        return format_messages_openai(messages, system_instruction)

    @staticmethod
    def _parse_tool_calls(raw: Any) -> List[Dict[str, Any]]:
        """Normalize OpenAI tool_calls into the SDK's neutral call shape.

        Accepts both the SDK's objects and plain dicts (e.g. from JSON).
        """

        def field(obj: Any, key: str) -> Any:
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        calls: List[Dict[str, Any]] = []
        for tc in raw or []:
            func = field(tc, "function")
            raw_args = field(func, "arguments") or "{}"
            if isinstance(raw_args, dict):
                args = raw_args
            else:
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "OpenAI tool_call arguments failed to parse "
                        "for tool=%s id=%s (arguments redacted; %d characters; %s)",
                        field(func, "name"),
                        field(tc, "id") or "<unknown>",
                        len(str(raw_args)),
                        type(exc).__name__,
                    )
                    args = {"__parse_error": str(exc)}
            calls.append(
                {
                    "id": field(tc, "id"),
                    "name": field(func, "name"),
                    "arguments": args,
                }
            )
        return calls

    @staticmethod
    def _field(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    @classmethod
    def _stage_stream_tool_calls(
        cls, pending: Dict[int, Dict[str, Any]], raw: Any
    ) -> tuple[
        tuple[tuple[int, str, str, str, bool], ...],
        tuple[RawToolCallFragment, ...],
    ]:
        staged: list[tuple[int, str, str, str, bool]] = []
        budget_fragments: list[RawToolCallFragment] = []
        new_indices: set[int] = set()
        for fallback_index, tc in enumerate(raw or []):
            index = cls._field(tc, "index")
            if not isinstance(index, int):
                index = fallback_index
            starts_call = index not in pending and index not in new_indices
            if starts_call:
                new_indices.add(index)
            tool_call_id = str(cls._field(tc, "id") or "")
            func = cls._field(tc, "function")
            name = str(cls._field(func, "name") or "")
            arguments = str(cls._field(func, "arguments") or "")
            staged.append((index, tool_call_id, name, arguments, starts_call))
            budget_fragments.append(
                RawToolCallFragment(
                    key=index,
                    starts_call=starts_call,
                    id_fragment=tool_call_id,
                    name_fragment=name,
                    arguments_fragment=arguments,
                )
            )
        return tuple(staged), tuple(budget_fragments)

    @staticmethod
    def _append_stream_tool_calls(
        pending: Dict[int, Dict[str, Any]],
        staged: tuple[tuple[int, str, str, str, bool], ...],
    ) -> None:
        for index, tool_call_id, name, arguments, _ in staged:
            current = pending.setdefault(
                index,
                {
                    "id": LinearStringParts(),
                    "name": LinearStringParts(),
                    "arguments": LinearStringParts(),
                },
            )
            current["id"].append(tool_call_id)
            current["name"].append(name)
            current["arguments"].append(arguments)

    @staticmethod
    def _finalize_stream_tool_calls(
        pending: Dict[int, Dict[str, Any]],
        budget: ProviderResponseBudget | None = None,
    ) -> List[Dict[str, Any]]:
        """Build the neutral tool-call payload from the streamed accumulator.

        When the model's tool-arg JSON does not parse, we do two things:

        - log only the tool identity, payload length, and exception type,
        - return ``{"__parse_error": str(exc)}`` so the planner fails the
          call closed via the existing sentinel in ``planner.py``.

        The raw text is not copied into the event payload because events are
        persisted, replayed, and surfaced to UI, and the stream can contain
        whatever the model echoed back. ``str(exc)`` from ``JSONDecodeError``
        carries only line/column context, not a slice of the payload.
        """
        calls: List[Dict[str, Any]] = []
        for _, item in sorted(pending.items()):
            name = (
                item["name"].join()
                if isinstance(item["name"], LinearStringParts)
                else item["name"]
            )
            if not name:
                continue
            call_id = (
                item["id"].join()
                if isinstance(item["id"], LinearStringParts)
                else item["id"]
            )
            raw = (
                item["arguments"].join()
                if isinstance(item["arguments"], LinearStringParts)
                else item["arguments"]
            ) or "{}"
            if budget is not None:
                budget.record_tool_argument_join()
            try:
                args: Dict[str, Any] = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "OpenAI streaming tool_call arguments failed to parse "
                    "for tool=%s id=%s (arguments redacted; %d characters; %s)",
                    name,
                    call_id or "<unknown>",
                    len(raw),
                    type(exc).__name__,
                )
                args = {"__parse_error": str(exc)}
            calls.append(
                {
                    "id": call_id or None,
                    "name": name,
                    "arguments": args,
                }
            )
        return calls

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
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._build_messages(messages, system_instruction),
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = to_openai(tools)
        if response_format:
            kwargs["response_format"] = response_format

        _raise_if_cancelled(cancellation_token)

        request_error = None
        try:
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - surface as a provider error
            logger.error(
                "OpenAI API request failed (%s; details redacted)", type(e).__name__
            )
            request_error = provider_error_from_exception(
                service="openai", action="request", error=e
            )

        if request_error is not None:
            raise request_error from None

        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = self._parse_tool_calls(getattr(message, "tool_calls", None))
        accepted = ProviderResponseBudget(response_limits).accept_normalized(
            text, tool_calls
        )
        text = accepted.delta
        tool_calls = list(accepted.tool_calls)

        usage = getattr(response, "usage", None)
        metrics = TokenMetrics(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
        )
        metadata = ModelMetadata(provider_name="openai", model_name=self.model_name)

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
        """Stream chat completions, yielding text deltas and tool calls.

        Cancellation is checked before the request and before each chunk is
        consumed. A set token raises :class:`asyncio.CancelledError` so the
        caller can distinguish cancellation from a normal end-of-stream. The
        post-loop tool-call finalization is intentionally skipped on
        cancellation; partially-accumulated tool calls are discarded.
        """
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._build_messages(messages, system_instruction),
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = to_openai(tools)

        _raise_if_cancelled(cancellation_token)

        open_error = None
        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "OpenAI streaming API request failed (%s; details redacted)",
                type(e).__name__,
            )
            open_error = provider_error_from_exception(
                service="openai", action="stream", error=e
            )

        if open_error is not None:
            raise open_error from None

        pending_tool_calls: Dict[int, Dict[str, Any]] = {}
        budget = ProviderResponseBudget(response_limits)

        iteration_error = None
        try:
            async for chunk in stream:
                _raise_if_cancelled(cancellation_token)

                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    metrics = TokenMetrics(
                        prompt_tokens=getattr(usage, "prompt_tokens", 0),
                        completion_tokens=getattr(usage, "completion_tokens", 0),
                        total_tokens=getattr(usage, "total_tokens", 0),
                    )
                    yield ModelResponseChunk(
                        metrics=metrics,
                        cost_usd=(
                            calculate_cost_usd(
                                self.model_name,
                                metrics.prompt_tokens,
                                metrics.completion_tokens,
                            )
                            if lookup_cost(self.model_name) is not None
                            else None
                        ),
                    )
                    continue

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                staged, raw_fragments = self._stage_stream_tool_calls(
                    pending_tool_calls, getattr(delta, "tool_calls", None)
                )
                budget.accept_raw(text=text, tool_fragments=raw_fragments)
                self._append_stream_tool_calls(pending_tool_calls, staged)
                if text:
                    yield ModelResponseChunk(delta=text, tool_calls=[])
        except ProviderOutputLimitError:
            await close_provider_stream(stream)
            capture_provider_diagnostics(budget.diagnostics)
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(
                "OpenAI streaming API iteration failed (%s; details redacted)",
                type(e).__name__,
            )
            iteration_error = provider_error_from_exception(
                service="openai", action="stream", error=e
            )

        if iteration_error is not None:
            capture_provider_diagnostics(budget.diagnostics)
            raise iteration_error from None

        tool_calls = self._finalize_stream_tool_calls(pending_tool_calls, budget)
        if tool_calls:
            yield ModelResponseChunk(delta="", tool_calls=cast(Any, tool_calls))
        capture_provider_diagnostics(budget.diagnostics)


register_provider("openai", OpenAIProvider)
