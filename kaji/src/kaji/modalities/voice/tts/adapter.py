"""Text-to-speech modality adapter."""

from __future__ import annotations

from typing import AsyncIterator


class TTSNotConfiguredError(RuntimeError):
    """Raised when TTS is requested but no provider is configured."""


class VoiceTTSAdapter:
    """Placeholder TTS adapter — configure a provider before use in production.

    Satisfies the ``TTSProvider`` protocol so it can stand in wherever a
    provider is expected, but every synthesis path raises
    ``TTSNotConfiguredError``. Selected when ``TTS_PROVIDER='none'``.
    """

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("text must not be empty")
        raise TTSNotConfiguredError("Voice TTS provider is not configured")

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not text.strip():
            raise ValueError("text must not be empty")
        raise TTSNotConfiguredError("Voice TTS provider is not configured")
        yield b""  # pragma: no cover - unreachable; makes this an async generator
