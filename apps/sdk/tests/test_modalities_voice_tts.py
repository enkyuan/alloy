"""Tests for the TTS provider factory and the placeholder adapter."""

import pytest

from agentkit.voice.tts import (
    TTSNotConfiguredError,
    VoiceTTSAdapter,
    get_tts_provider,
)
from agentkit.voice.event_models import AgentAudioChunk


def test_factory_defaults_to_placeholder_adapter():
    """With TTS_PROVIDER unset/'none', the factory returns the stub adapter."""
    provider = get_tts_provider("none")
    assert isinstance(provider, VoiceTTSAdapter)


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown TTS_PROVIDER"):
        get_tts_provider("not-a-provider")


def test_factory_selects_gemini():
    """'gemini' returns a provider satisfying the synthesize/stream surface."""
    provider = get_tts_provider("gemini")
    assert hasattr(provider, "synthesize")
    assert hasattr(provider, "stream")
    assert not isinstance(provider, VoiceTTSAdapter)


async def test_placeholder_synthesize_raises_when_not_configured():
    provider = VoiceTTSAdapter()
    with pytest.raises(TTSNotConfiguredError):
        await provider.synthesize("hello")


async def test_placeholder_rejects_empty_text():
    provider = VoiceTTSAdapter()
    with pytest.raises(ValueError):
        await provider.synthesize("   ")


async def test_placeholder_stream_raises_when_not_configured():
    provider = VoiceTTSAdapter()
    with pytest.raises(TTSNotConfiguredError):
        async for _ in provider.stream("hello"):
            pass


def test_agent_audio_chunk_model_defaults():
    chunk = AgentAudioChunk(audio=b"\x00\x01", user_id="u1")
    assert chunk.audio == b"\x00\x01"
    assert chunk.mime_type == "audio/pcm"
    assert chunk.seq == 0
    assert chunk.user_id == "u1"
