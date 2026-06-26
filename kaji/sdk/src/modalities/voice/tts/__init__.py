"""TTS subpackage — provider protocol, concrete providers, and a factory.

``get_tts_provider()`` selects a provider from settings (``TTS_PROVIDER``),
falling back to the placeholder adapter that raises until TTS is configured.
"""

from kaji.modalities.voice.tts.adapter import TTSNotConfiguredError, VoiceTTSAdapter
from kaji.modalities.voice.tts.base import TTSProvider

__all__ = [
    "GetTTSProvider",
    "TTSNotConfiguredError",
    "TTSProvider",
    "VoiceTTSAdapter",
]


def get_tts_provider(provider: str | None = None) -> TTSProvider:
    """Return a configured TTS provider.

    Args:
        provider: Override for ``settings.TTS_PROVIDER``. One of ``"none"``,
            ``"gemini"``, or ``"openai"``. Defaults to the configured value.

    Returns:
        A ``TTSProvider``. For ``"none"`` (the default), this is the
        ``VoiceTTSAdapter`` placeholder, whose ``synthesize`` raises
        ``TTSNotConfiguredError`` — text-only operation still works.
    """
    from kaji.core.config import settings

    name = (provider or settings.TTS_PROVIDER or "none").lower()

    if name == "gemini":
        from kaji.modalities.voice.tts.gemini_provider import GeminiTTSProvider

        return GeminiTTSProvider()
    if name == "openai":
        from kaji.modalities.voice.tts.openai_provider import OpenAITTSProvider

        return OpenAITTSProvider()
    if name == "none":
        return VoiceTTSAdapter()

    raise ValueError(
        f"Unknown TTS_PROVIDER: {name!r} (expected 'none', 'gemini', or 'openai')"
    )


GetTTSProvider = get_tts_provider
