"""OpenAI LLM provider.

Uses the official async OpenAI SDK (the same dependency the OpenAI TTS path
uses). Consumes the SDK's neutral tool payload and translates it to OpenAI's
function-tool format at this boundary via ``to_openai``. Kimi remains the
default provider; this is opt-in via ``AGENTKIT_MODEL_PROVIDER=openai``.
"""

from __future__ import annotations

import json
import logging
from importlib import import_module
from typing import Any, AsyncGenerator, Dict, List, Optional, cast

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
from agentkit.runtime.providers._translate import format_messages_openai
from agentkit.runtime.tools.payload import to_openai

logger = logging.getLogger(__name__)


class OpenAIProvider(ModelProvider):
    """OpenAI chat-completions provider with streaming and tool calls."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
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
            except ImportError as error:
                raise ProviderConfigError(
                    "OpenAI provider requires openai. Install agentkit[openai]."
                ) from error

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
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
            try:
                args = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                args = {}
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
    def _accumulate_stream_tool_calls(
        cls, pending: Dict[int, Dict[str, str]], raw: Any
    ) -> None:
        for fallback_index, tc in enumerate(raw or []):
            index = cls._field(tc, "index")
            if not isinstance(index, int):
                index = fallback_index
            current = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})

            tool_call_id = cls._field(tc, "id")
            if tool_call_id:
                current["id"] = str(tool_call_id)

            func = cls._field(tc, "function")
            name = cls._field(func, "name")
            if name:
                current["name"] += str(name)

            arguments = cls._field(func, "arguments")
            if arguments:
                current["arguments"] += str(arguments)

    @staticmethod
    def _finalize_stream_tool_calls(
        pending: Dict[int, Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for _, item in sorted(pending.items()):
            if not item["name"]:
                continue
            try:
                args = json.loads(item["arguments"] or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            calls.append(
                {
                    "id": item["id"] or None,
                    "name": item["name"],
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

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - surface as a provider error
            logger.error("OpenAI API error: %s", e)
            raise ProviderAPIError(f"OpenAI request failed: {e}") from e

        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = self._parse_tool_calls(getattr(message, "tool_calls", None))

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
        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": self._build_messages(messages, system_instruction),
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = to_openai(tools)

        try:
            stream = await self.client.chat.completions.create(**kwargs)
        except Exception as e:  # noqa: BLE001
            logger.error("OpenAI streaming API error: %s", e)
            raise ProviderAPIError(f"OpenAI stream failed: {e}") from e

        pending_tool_calls: Dict[int, Dict[str, str]] = {}

        async for chunk in stream:
            if cancellation_token and getattr(
                cancellation_token, "is_cancelled", False
            ):
                break

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = getattr(delta, "content", None) or ""
            self._accumulate_stream_tool_calls(
                pending_tool_calls, getattr(delta, "tool_calls", None)
            )
            if text:
                yield ModelResponseChunk(delta=text, tool_calls=[])

        tool_calls = self._finalize_stream_tool_calls(pending_tool_calls)
        if tool_calls:
            yield ModelResponseChunk(delta="", tool_calls=cast(Any, tool_calls))


register_provider("openai", OpenAIProvider)
