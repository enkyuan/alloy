"""Google Gemini AI service for conversational AI."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from google import genai

from app.core.config import settings

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

        self.api_key = settings.GEMINI_API_KEY
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set in environment variables")
            raise ValueError("GEMINI_API_KEY is required")

        logger.info("Initializing Gemini client...")
        self.client = genai.Client(api_key=self.api_key)
        self.model = "gemini-2.5-flash"
        logger.info("Gemini client initialized with model: %s", self.model)

    async def _get_active_cache(self, system_instruction: Optional[str], contents: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """Creates or retrieves a GCP Context Cache if tokens > 32K limit."""
        if len(contents) <= 2:
            return None
            
        import hashlib
        import json
        from google.genai import types
        
        # We cache everything except the very last interaction turn.
        cache_slice = contents[:-2]
        
        # Build deterministic hash 
        safe_tools = tools if tools else []
        cache_key_data = json.dumps({"sys": system_instruction, "history": cache_slice, "tools": safe_tools}, default=str)
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
                
            logger.info("Context exceeds 32K token minimum (%s). Generating native GCP Cache to slash costs.", token_info.total_tokens)
            
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
                config=cache_config  # type: ignore
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
                contents=text
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
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

            config: Any = {"temperature": temperature}
            
            # Context Caching Heuristics
            active_contents = contents
            cache_name = await self._get_active_cache(system_instruction, contents, tools)
            if cache_name:
                config["cached_content"] = cache_name
                # Only pass the un-cached remainder (last two messages) to the LLM
                active_contents = contents[-2:] if len(contents) >= 2 else contents
            else:
                if system_instruction:
                    config["system_instruction"] = system_instruction
                    logger.debug("Using system instruction: %s...", system_instruction[:100])
                if tools:
                    config["tools"] = tools

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

