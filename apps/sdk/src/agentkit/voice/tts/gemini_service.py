"""Gemini TTS service — holds the client/config for speech synthesis.

Mirrors the STT ``SonioxService`` shape: this class owns credentials and
builds the provider request config; the streaming/synthesis transport lives in
``gemini_provider``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agentkit.core.config import settings

logger = logging.getLogger(__name__)


class GeminiTTSService:
    """Configuration + client holder for Gemini text-to-speech."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.voice = voice or settings.TTS_VOICE
        self.model = model or settings.TTS_MODEL
        self._client: Any = None

        if not self.api_key:
            logger.warning(
                "GEMINI_API_KEY is not set. Gemini TTS will not be available."
            )

    @property
    def client(self) -> Any:
        """Lazily construct the genai client (only when actually used)."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is required for Gemini TTS.")
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def build_config(self) -> Any:
        """Build the ``GenerateContentConfig`` for an audio response."""
        from google.genai import types

        return types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice,
                    )
                )
            ),
        )
