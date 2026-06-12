"""Google Gemini AI service for conversational AI."""

import asyncio
import logging
import hashlib
import json

from typing import Any, AsyncGenerator, Dict, List, Optional

from google import genai
from google.genai import types

from agentkit.core.config import get_settings
from agentkit.runtime.providers._translate import to_gemini_role

logger = logging.getLogger(__name__)


class GeminiService:
    """Service for Google Gemini AI operations."""

    _active_caches: Dict[str, str] = {}

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Gemini service.

        Args:
            api_key: Optional API key. If not provided, uses GEMINI_API_KEY from settings.
        """
        if genai is None:
            raise ImportError(
                "google-genai package is not installed. "
                "Install it with: pip install google-genai"
            )

        self.api_key = get_settings().GEMINI_API_KEY
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set in environment variables")
            raise ValueError("GEMINI_API_KEY is required")

        logger.info("Initializing Gemini client...")
        self.client = genai.Client(api_key=self.api_key)
        self.model = get_settings().GEMINI_MODEL
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
            {"sys": system_instruction, "history": cache_slice, "tools": safe_tools},
            default=str,
        )
        cache_hash = hashlib.md5(cache_key_data.encode()).hexdigest()

        if cache_hash in GeminiService._active_caches:
            return GeminiService._active_caches[cache_hash]

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
                config=cache_config,  # type: ignore
            )
            if not cache.name:
                return None
            GeminiService._active_caches[cache_hash] = str(cache.name)
            return str(cache.name)
        except Exception as e:
            logger.warning("Failed to provision GCP Context Cache: %s", e)
            return None

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a response from Gemini."""
        try:
            config = self._build_generation_config(
                temperature=temperature,
                system_instruction=system_instruction,
                max_tokens=max_tokens,
            )

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=config,
            )

            logger.info("Generated Gemini response for prompt: %s...", prompt[:50])
            return response.text or ""

        except Exception as e:
            logger.error("Failed to generate Gemini response: %s", e, exc_info=True)
            raise

    async def embed_text(self, text: str) -> List[float]:
        """Embed text directly through Gemini models natively"""
        try:
            response = await asyncio.to_thread(
                self.client.models.embed_content,
                model="text-embedding-004",
                contents=text,
            )
            if not response.embeddings or not response.embeddings[0].values:
                return []
            return list(response.embeddings[0].values)
        except Exception as e:
            logger.error("Failed to embed text: %s", e)
            raise

    async def generate_chat_response(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
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
        try:
            logger.info("Generating chat response with %s messages", len(messages))
            logger.debug("Messages: %s", messages)

            contents = []
            for msg in messages:
                role = to_gemini_role(msg["role"])
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

            config: Any = {"temperature": temperature}

            # Always include system_instruction and tools regardless of caching.
            if system_instruction:
                config["system_instruction"] = system_instruction
                logger.debug(
                    "Using system instruction: %s...", system_instruction[:100]
                )
            if tools:
                config["tools"] = tools

            # Context Caching Heuristics
            active_contents = contents
            cache_name = await self._get_active_cache(
                system_instruction, contents, tools
            )
            if cache_name:
                config["cached_content"] = cache_name
                # Only pass the un-cached remainder (last two messages) to the LLM
                active_contents = contents[-2:] if len(contents) >= 2 else contents

            logger.info("Calling Gemini API with model: %s", self.model)
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=active_contents,
                config=config,
            )

            logger.info("Successfully generated chat response")
            return response

        except Exception as e:
            logger.error("Failed to generate chat response: %s", e, exc_info=True)
            logger.error("Error type: %s", type(e).__name__)
            logger.error("Messages that failed: %s", messages)
            raise

    async def generate_streaming_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
    ):
        """Generate a streaming response from Gemini."""
        try:
            config = self._build_generation_config(
                temperature=temperature,
                system_instruction=system_instruction,
            )

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

        except Exception as e:
            logger.error(
                f"Failed to generate streaming response: {str(e)}", exc_info=True
            )
            raise

    async def generate_chat_stream(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        """Stream a chat response over full message history, with tools.

        Mirrors :meth:`generate_chat_response` (full history + system
        instruction + tools) but yields raw Gemini stream chunks so the caller
        can extract both text deltas and function-call parts. Context caching is
        intentionally not applied on the streaming path.
        """
        try:
            contents = []
            for msg in messages:
                role = to_gemini_role(msg["role"])
                contents.append(
                    {"role": role, "parts": [{"text": msg.get("content", "")}]}
                )

            config: Any = {"temperature": temperature}
            if system_instruction:
                config["system_instruction"] = system_instruction
            if tools:
                config["tools"] = tools

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

        except Exception as e:
            logger.error("Failed to generate chat stream: %s", e, exc_info=True)
            raise

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


# Singleton instance
gemini_service: Optional[GeminiService] = None


def get_gemini_service() -> GeminiService:
    """Get or create Gemini service instance."""
    global gemini_service
    if gemini_service is None:
        gemini_service = GeminiService()
    return gemini_service


from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.providers.registry import register_provider
from agentkit.runtime.providers.types import (
    GenerateResponse,
    ModelMetadata,
    ModelResponseChunk,
    TokenMetrics,
)


class GeminiProvider(ModelProvider):
    """Gemini provider implementing the generic ModelProvider interface."""

    def __init__(self, **kwargs):
        self.service = get_gemini_service()

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

        # Translate the neutral tool payload to Gemini's function-declaration form.
        from agentkit.runtime.tools.payload import to_gemini

        gemini_tools = to_gemini(tools) or None if tools else None

        response = await self.service.generate_chat_response(
            messages=messages,
            system_instruction=system_instruction,
            temperature=temperature,
            tools=gemini_tools,
        )

        text = response.text or ""

        # Extract tool calls using the helper
        from agentkit.runtime.tools.function_calls import (
            extract_response_function_calls,
        )

        function_calls = extract_response_function_calls(response)

        tool_calls = []
        for fc in function_calls:
            import uuid

            args = dict(fc.args) if fc.args else {}
            tool_calls.append(
                {"id": str(uuid.uuid4()), "name": fc.name, "arguments": args}
            )

        metadata = ModelMetadata(provider_name="gemini", model_name=self.service.model)

        # Token metrics estimation or extraction if available
        metrics = TokenMetrics()
        if hasattr(response, "usage_metadata"):
            usage = response.usage_metadata
            metrics.prompt_tokens = getattr(usage, "prompt_token_count", 0)
            metrics.completion_tokens = getattr(usage, "candidates_token_count", 0)
            metrics.total_tokens = getattr(usage, "total_token_count", 0)

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
        import uuid

        from agentkit.runtime.tools.function_calls import (
            extract_response_function_calls,
        )
        from agentkit.runtime.tools.payload import to_gemini

        # Stream over the full message history with tools, so streaming has
        # parity with the non-streaming generate(): both keep context and can
        # surface tool calls.
        gemini_tools = to_gemini(tools) if tools else None

        async for chunk in self.service.generate_chat_stream(
            messages=messages,
            system_instruction=system_instruction,
            temperature=temperature,
            tools=gemini_tools,
        ):
            if cancellation_token and getattr(
                cancellation_token, "is_cancelled", False
            ):
                break

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
                    {"id": str(uuid.uuid4()), "name": fc.name, "arguments": args}
                )

            if delta or tool_calls:
                yield ModelResponseChunk(delta=delta, tool_calls=tool_calls)


register_provider("gemini", GeminiProvider)
