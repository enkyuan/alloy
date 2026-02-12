"""Google Gemini AI service for conversational AI."""

import logging
from typing import Any, Dict, List, Optional

from google import genai

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiService:
    """Service for Google Gemini AI operations."""

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

        self.api_key = api_key or settings.GEMINI_API_KEY
        if not self.api_key:
            logger.error("GEMINI_API_KEY is not set in environment variables")
            raise ValueError("GEMINI_API_KEY is required")

        logger.info("Initializing Gemini client...")
        self.client = genai.Client(api_key=self.api_key)
        self.model = settings.GEMINI_MODEL
        logger.info(f"Gemini client initialized with model: {self.model}")

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate a response from Gemini.

        Args:
            prompt: User prompt/message
            system_instruction: Optional system instruction to guide the model
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response

        Raises:
            Exception: If generation fails
        """
        try:
            config = self._build_generation_config(
                temperature=temperature,
                system_instruction=system_instruction,
                max_tokens=max_tokens,
            )

            response = self.client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )

            logger.info(f"Generated Gemini response for prompt: {prompt[:50]}...")
            return response.text or ""

        except Exception as e:
            logger.error(f"Failed to generate Gemini response: {str(e)}", exc_info=True)
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
            messages: List of message dicts with 'role' and 'content' keys
            system_instruction: Optional system instruction
            temperature: Sampling temperature
            tools: Optional list of tool definitions

        Returns:
            Generated response object (containing text or function calls)
        """
        try:
            logger.info(f"Generating chat response with {len(messages)} messages")
            logger.debug(f"Messages: {messages}")

            # Convert messages to Gemini format
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

            config: Any = {"temperature": temperature}
            if system_instruction:
                config["system_instruction"] = system_instruction
                logger.debug(f"Using system instruction: {system_instruction[:100]}...")

            if tools:
                config["tools"] = tools

            logger.info(f"Calling Gemini API with model: {self.model}")
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=config
            )

            logger.info(f"Successfully generated chat response")
            # Return the full response object to handle function calls
            return response

        except Exception as e:
            logger.error(f"Failed to generate chat response: {str(e)}", exc_info=True)
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Messages that failed: {messages}")
            raise

    async def generate_streaming_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
    ):
        """Generate a streaming response from Gemini.

        Args:
            prompt: User prompt/message
            system_instruction: Optional system instruction
            temperature: Sampling temperature

        Yields:
            Text chunks as they are generated
        """
        try:
            config = self._build_generation_config(
                temperature=temperature,
                system_instruction=system_instruction,
            )

            response = self.client.models.generate_content_stream(
                model=self.model, contents=prompt, config=config
            )

            for chunk in response:
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
    """Get or create Gemini service instance.

    Returns:
        GeminiService instance
    """
    global gemini_service
    if gemini_service is None:
        gemini_service = GeminiService()
    return gemini_service
