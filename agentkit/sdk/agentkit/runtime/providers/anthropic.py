"""Anthropic LLM provider.

Uses the official async Anthropic SDK. Translates the SDK's neutral tool payload
to Anthropic's ``input_schema`` format via ``to_anthropic``. Enable with
``AGENTKIT_MODEL_PROVIDER=anthropic``.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from agentkit.core.config import get_settings
from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.providers.errors import ProviderAPIError, ProviderConfigError
from agentkit.runtime.providers.registry import register_provider
from agentkit.runtime.providers.types import (
    GenerateResponse,
    ModelMetadata,
    ModelResponseChunk,
    TokenMetrics,
)
from agentkit.runtime.providers._translate import format_messages_anthropic
from agentkit.runtime.tools.payload import to_anthropic

logger = logging.getLogger(__name__)


class AnthropicProvider(ModelProvider):
    """Anthropic Messages API provider with streaming and tool use."""

    def __init__(self, **kwargs: Any) -> None:
        settings = get_settings()
        self.api_key = settings.ANTHROPIC_API_KEY
        self.model_name = settings.ANTHROPIC_MODEL
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
                from anthropic import AsyncAnthropic
            except ImportError as error:
                raise ProviderConfigError(
                    "Anthropic provider requires anthropic. Install agentkit[anthropic]."
                ) from error

            self._client = AsyncAnthropic(api_key=self.api_key)
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

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
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

        try:
            response = await self.client.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error("Anthropic API error: %s", e)
            raise ProviderAPIError(f"Anthropic request failed: {e}") from e

        text, tool_calls = self._parse_tool_use(response.content)

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
            text=text, tool_calls=tool_calls, metadata=metadata, metrics=metrics
        )

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
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

        try:
            stream = self.client.messages.stream(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error("Anthropic streaming API error: %s", e)
            raise ProviderAPIError(f"Anthropic stream failed: {e}") from e

        # Accumulate tool_use blocks — Anthropic streams them in deltas that
        # must be reassembled before the arguments are valid JSON.
        pending_tool: Dict[str, Any] = {}

        async with stream as s:
            async for event in s:
                if cancellation_token and getattr(
                    cancellation_token, "is_cancelled", False
                ):
                    break

                event_type = getattr(event, "type", None)

                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block and getattr(block, "type", None) == "tool_use":
                        pending_tool = {
                            "id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                            "arguments_raw": "",
                        }

                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    delta_type = getattr(delta, "type", None)
                    if delta_type == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield ModelResponseChunk(delta=text)
                    elif delta_type == "input_json_delta":
                        pending_tool["arguments_raw"] = pending_tool.get(
                            "arguments_raw", ""
                        ) + getattr(delta, "partial_json", "")

                elif event_type == "content_block_stop" and pending_tool:
                    import json

                    try:
                        args = json.loads(pending_tool.get("arguments_raw", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    yield ModelResponseChunk(
                        delta="",
                        tool_calls=[
                            {
                                "id": pending_tool.get("id"),
                                "name": pending_tool.get("name"),
                                "arguments": args,
                            }
                        ],
                    )
                    pending_tool = {}


register_provider("anthropic", AnthropicProvider)
