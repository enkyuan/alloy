"""OpenAI TTS service — holds the client/config for speech synthesis.

Mirrors :class:`GeminiTTSService`: this class owns credentials and the chosen
voice/model; the streaming/synthesis transport lives in ``openai_provider``.
Unlike the Gemini SDK, the OpenAI SDK is natively async, so the provider calls
it directly without a worker thread.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agentkit.core.config import settings

logger = logging.getLogger(__name__)


class OpenAITTSService:
    """Configuration + client holder for OpenAI text-to-speech."""

    DEFAULT_VOICE = "alloy"
    DEFAULT_MODEL = "gpt-4o-mini-tts"
    # OpenAI streams raw PCM nicely for low-latency playback; callers can
    # override via the response format if they need a container instead.
    RESPONSE_FORMAT = "pcm"

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.voice = voice or settings.TTS_VOICE or self.DEFAULT_VOICE
        self.model = model or settings.TTS_MODEL or self.DEFAULT_MODEL
        self._client: Any = None

        if not self.api_key:
            logger.warning(
                "OPENAI_API_KEY is not set. OpenAI TTS will not be available."
            )

    @property
    def client(self) -> Any:
        """Lazily construct the async OpenAI client (only when actually used)."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY is required for OpenAI TTS.")
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client
