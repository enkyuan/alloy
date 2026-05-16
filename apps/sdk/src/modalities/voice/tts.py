"""Text-to-speech modality adapter."""

from __future__ import annotations


class TTSNotConfiguredError(RuntimeError):
    """Raised when TTS is requested but no provider is configured."""


class VoiceTTSAdapter:
    """Placeholder TTS adapter — configure a provider before use in production."""

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("text must not be empty")
        raise TTSNotConfiguredError("Voice TTS provider is not configured")
