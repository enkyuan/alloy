"""Google Gemini AI service for conversational AI."""

import asyncio
import hashlib
import json
import logging

from importlib import import_module
from time import monotonic
from typing import Any, AsyncGenerator, Dict, List, Optional

from kaji.core.config import get_settings
from kaji.runtime.providers.base import (
    ModelProvider,
    ProviderResponseBudget,
    capture_provider_diagnostics,
)
from kaji.runtime.providers.errors import (
    ProviderConfigError,
    ProviderError,
    provider_error_from_exception,
)
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
from kaji.runtime.providers._translate import (
    format_messages_gemini,
    split_system_for_gemini,
)
from kaji.core.determinism import IdFactory, SYSTEM_ID_FACTORY

logger = logging.getLogger(__name__)

_CONTEXT_CACHE_LOCAL_TTL_SECONDS = 9 * 60


def _gemini_error(action: str, error: Exception) -> ProviderError:
    return provider_error_from_exception(
        service="gemini",
        action=action,
        error=error,
    )


class GeminiService:
    """Service for Google Gemini AI operations."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Gemini service.

        Args:
            api_key: Optional API key. If not provided, uses GEMINI_API_KEY from settings.
        """
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set in environment variables")
            raise ProviderConfigError("GEMINI_API_KEY is required", service="gemini")

        logger.info("Initializing Gemini client...")
        try:
            genai = import_module("google.genai")
        except ImportError:
            raise ProviderConfigError(
                "Gemini provider requires google-genai. Install kaji[gemini]."
            ) from None

        self.client = genai.Client(api_key=self.api_key)
        self.model = settings.GEMINI_MODEL
        self.embedding_model = settings.GEMINI_EMBEDDING_MODEL
        self._active_caches: Dict[str, tuple[str, float]] = {}
        logger.info("Gemini client initialized with model: %s", self.model)

    async def _get_active_cache(
        self,
        system_instruction: Optional[str],
        contents: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> Optional[str]:
        """Creates or retrieves a GCP Context Cache if tokens > 32K limit."""
        if len(contents) <= 2:
            return None

        # We cache everything except the very last interaction turn.
        cache_slice = contents[:-2]

        # Build deterministic hash
        safe_tools = tools if tools else []
        cache_key_data = json.dumps(
            {
                "model": self.model,
                "sys": system_instruction,
                "history": cache_slice,
                "tools": safe_tools,
            },
            default=str,
        )
        cache_hash = hashlib.sha256(cache_key_data.encode()).hexdigest()

        active_cache = self._active_caches.get(cache_hash)
        if active_cache is not None:
            cache_name, expires_at = active_cache
            if monotonic() < expires_at:
                return cache_name
            del self._active_caches[cache_hash]

        # Count tokens of the slice
        try:
            token_info = await asyncio.to_thread(
                self.client.models.count_tokens,
                model=self.model,
                contents=cache_slice,
            )
            if (token_info.total_tokens or 0) < 32768:
                return None

            logger.info(
                "Context exceeds 32K token minimum (%s). Generating native GCP Cache to slash costs.",
                token_info.total_tokens,
            )

            cache_config: Dict[str, Any] = {
                "system_instruction": system_instruction,
                "contents": cache_slice,
                "ttl": "600s",
            }
            # Add tools to config only if they exist
            if tools:
                cache_config["tools"] = tools

            cache = await asyncio.to_thread(
                self.client.caches.create,
                model=self.model,
                config=cache_config,
            )
            if not cache.name:
                return None
            cache_name = str(cache.name)
            self._active_caches[cache_hash] = (
                cache_name,
                monotonic() + _CONTEXT_CACHE_LOCAL_TTL_SECONDS,
            )
            return cache_name
        except Exception as error:
            logger.warning(
                "Failed to provision GCP Context Cache (%s; details redacted)",
                type(error).__name__,
            )
            return None

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a response from Gemini."""
        config = self._build_generation_config(
            temperature=temperature,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
        )

        request_error = None
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=config,
            )
        except Exception as error:
            request_error = _gemini_error("generate", error)

        if request_error is not None:
            raise request_error from None

        return response.text or ""

    async def embed_text(self, text: str) -> List[float]:
        """Embed text directly through Gemini models natively"""
        request_error = None
        try:
            response = await asyncio.to_thread(
                self.client.models.embed_content,
                model=self.embedding_model,
                contents=text,
            )
        except Exception as error:
            request_error = _gemini_error("embed", error)
        if request_error is not None:
            raise request_error from None
        if not response.embeddings or not response.embeddings[0].values:
            return []
        return list(response.embeddings[0].values)

    async def embed(self, text: str) -> List[float]:
        """Implement the retriever ``Embedder`` protocol."""
        return await self.embed_text(text)

    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Generate a response in a chat context.

        Args:
            messages: List of message dicts
            system_instruction: Optional system instruction
            temperature: Sampling temperature
            tools: Optional list of tool definitions

        Returns:
            Generated response object
        """
        contents = format_messages_gemini(messages)

        config: Any = {"temperature": temperature}
        if system_instruction:
            config["system_instruction"] = system_instruction
        if tools:
            config["tools"] = tools
        if max_tokens:
            config["max_output_tokens"] = max_tokens

        # Context Caching Heuristics
        active_contents = contents
        cache_name = await self._get_active_cache(system_instruction, contents, tools)
        if cache_name:
            config["cached_content"] = cache_name
            # Only pass the un-cached remainder (last two messages) to the LLM
            active_contents = contents[-2:] if len(contents) >= 2 else contents

        request_error = None
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=active_contents,
                config=config,
            )
        except Exception as error:
            request_error = _gemini_error("chat", error)
        if request_error is not None:
            raise request_error from None
        return response

    async def generate_streaming_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
    ):
        """Generate a streaming response from Gemini."""
        config = self._build_generation_config(
            temperature=temperature,
            system_instruction=system_instruction,
        )

        stream_error = None
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content_stream,
                model=self.model,
                contents=prompt,
                config=config,
            )
            iterator = iter(response)
            while True:
                chunk = await asyncio.to_thread(lambda: next(iterator, None))
                if chunk is None:
                    break
                if chunk.text:
                    yield chunk.text
        except Exception as error:
            stream_error = _gemini_error("stream", error)

        if stream_error is not None:
            raise stream_error from None

    async def generate_chat_stream(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
    ):
        """Stream a chat response over full message history, with tools.

        Mirrors :meth:`generate_chat_response` (full history + system
        instruction + tools) but yields raw Gemini stream chunks so the caller
        can extract both text deltas and function-call parts. Context caching is
        intentionally not applied on the streaming path.
        """
        contents = format_messages_gemini(messages)

        config: Any = {"temperature": temperature}
        if system_instruction:
            config["system_instruction"] = system_instruction
        if tools:
            config["tools"] = tools
        if max_tokens:
            config["max_output_tokens"] = max_tokens

        stream_error = None
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content_stream,
                model=self.model,
                contents=contents,
                config=config,
            )
            iterator = iter(response)
            while True:
                chunk = await asyncio.to_thread(lambda: next(iterator, None))
                if chunk is None:
                    break
                yield chunk
        except Exception as error:
            stream_error = _gemini_error("stream", error)

        if stream_error is not None:
            raise stream_error from None

    def _build_generation_config(
        self,
        temperature: float,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Build a Gemini generation config shared across response methods."""
        config: Any = {"temperature": temperature}
        if max_tokens:
            config["max_output_tokens"] = max_tokens
        if system_instruction:
            config["system_instruction"] = system_instruction
        return config


class GeminiProvider(ModelProvider):
    """Gemini provider implementing the generic ModelProvider interface."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        service: Optional[GeminiService] = None,
        id_factory: Optional[IdFactory] = None,
    ) -> None:
        if api_key is not None and service is not None:
            raise ValueError("api_key and service are mutually exclusive")
        self._id_factory = id_factory or SYSTEM_ID_FACTORY
        self.service = (
            service if service is not None else GeminiService(api_key=api_key)
        )

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
        # Translate the neutral tool payload to Gemini's function-declaration form.
        from kaji.runtime.tools.payload import to_gemini

        gemini_tools = to_gemini(tools) or None if tools else None

        # Peel system messages out of the history; Gemini routes system text
        # via the top-level system_instruction param.
        inline_system, chat_messages = split_system_for_gemini(messages)
        effective_system = system_instruction or inline_system

        _raise_if_cancelled(cancellation_token)

        response = await self.service.generate_chat_response(
            messages=chat_messages,
            system_instruction=effective_system,
            temperature=temperature,
            tools=gemini_tools,
            max_tokens=max_tokens,
        )

        text = response.text or ""

        # Extract tool calls using the helper
        from kaji.runtime.tools.function_calls import (
            extract_response_function_calls,
        )

        function_calls = extract_response_function_calls(response)

        tool_calls = []
        for fc in function_calls:
            args = dict(fc.args) if fc.args else {}
            tool_calls.append(
                {
                    "id": self._id_factory.next("tool_call"),
                    "name": fc.name,
                    "arguments": args,
                }
            )

        metadata = ModelMetadata(provider_name="gemini", model_name=self.service.model)

        # Token metrics estimation or extraction if available
        metrics = TokenMetrics()
        if hasattr(response, "usage_metadata"):
            usage = response.usage_metadata
            metrics.prompt_tokens = getattr(usage, "prompt_token_count", 0)
            metrics.completion_tokens = getattr(usage, "candidates_token_count", 0)
            metrics.total_tokens = getattr(usage, "total_token_count", 0)

        accepted = ProviderResponseBudget(response_limits).accept_normalized(
            text, tool_calls
        )
        return GenerateResponse(
            text=accepted.delta,
            tool_calls=list(accepted.tool_calls),
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
        response_limits: Optional[ProviderResponseLimits] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        from kaji.runtime.tools.function_calls import (
            extract_response_function_calls,
        )
        from kaji.runtime.tools.payload import to_gemini

        # Stream over the full message history with tools, so streaming has
        # parity with the non-streaming generate(): both keep context and can
        # surface tool calls.
        gemini_tools = to_gemini(tools) if tools else None

        inline_system, chat_messages = split_system_for_gemini(messages)
        effective_system = system_instruction or inline_system

        _raise_if_cancelled(cancellation_token)

        budget = ProviderResponseBudget(response_limits)
        async for chunk in self.service.generate_chat_stream(
            messages=chat_messages,
            system_instruction=effective_system,
            temperature=temperature,
            tools=gemini_tools,
            max_tokens=max_tokens,
        ):
            _raise_if_cancelled(cancellation_token)

            # `chunk.text` is a property that can raise when the chunk's parts
            # are function calls rather than text, so access it defensively.
            try:
                delta = chunk.text or ""
            except Exception:
                delta = ""

            tool_calls = []
            for fc in extract_response_function_calls(chunk):
                args = dict(fc.args) if fc.args else {}
                tool_calls.append(
                    {
                        "id": self._id_factory.next("tool_call"),
                        "name": fc.name,
                        "arguments": args,
                    }
                )

            if delta or tool_calls:
                accepted = budget.accept_normalized(delta, tool_calls)
                yield ModelResponseChunk(
                    delta=accepted.delta,
                    tool_calls=list(accepted.tool_calls),
                )
        capture_provider_diagnostics(budget.diagnostics)


register_provider("gemini", GeminiProvider)
