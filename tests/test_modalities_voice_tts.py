"""Tests for the TTS provider factory and the placeholder adapter."""

import pytest

from agentkit.modalities.voice.tts import (
    TTSNotConfiguredError,
    VoiceTTSAdapter,
    get_tts_provider,
)
from agentkit.modalities.voice.event_models import AgentAudioChunk


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


def test_factory_selects_openai():
    """'openai' returns a provider satisfying the synthesize/stream surface."""
    provider = get_tts_provider("openai")
    assert hasattr(provider, "synthesize")
    assert hasattr(provider, "stream")
    assert not isinstance(provider, VoiceTTSAdapter)


def test_factory_is_case_insensitive():
    from agentkit.modalities.voice.tts.openai_provider import OpenAITTSProvider

    assert isinstance(get_tts_provider("OpenAI"), OpenAITTSProvider)


def test_providers_use_their_own_voice_model_defaults():
    """With TTS_VOICE/TTS_MODEL unset, each provider falls back to its own
    default rather than another provider's value."""
    from agentkit.modalities.voice.tts.gemini_service import GeminiTTSService
    from agentkit.modalities.voice.tts.openai_service import OpenAITTSService

    gemini = GeminiTTSService(api_key="x")
    openai = OpenAITTSService(api_key="x")

    assert gemini.voice == GeminiTTSService.DEFAULT_VOICE
    assert gemini.model == GeminiTTSService.DEFAULT_MODEL
    assert openai.voice == OpenAITTSService.DEFAULT_VOICE
    assert openai.model == OpenAITTSService.DEFAULT_MODEL
    # The two providers must not share defaults.
    assert gemini.voice != openai.voice
    assert gemini.model != openai.model


async def test_openai_provider_rejects_empty_text():
    from agentkit.modalities.voice.tts.openai_provider import OpenAITTSProvider

    provider = OpenAITTSProvider()
    with pytest.raises(ValueError):
        await provider.synthesize("   ")


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


def test_agent_audio_chunk_roundtrips_via_base64():
    chunk = AgentAudioChunk.from_bytes(b"\x00\x01\x02", seq=3, user_id="u1")
    assert chunk.to_bytes() == b"\x00\x01\x02"
    assert chunk.mime_type == "audio/pcm"
    assert chunk.seq == 3
    assert chunk.user_id == "u1"
    # Must be JSON-serializable for the Redis envelope + websocket.send_json.
    import json

    json.dumps(chunk.model_dump(mode="json"))


class _FakeProvider:
    """A TTS provider that yields canned chunks (satisfies the protocol)."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def synthesize(self, text: str) -> bytes:
        return b"".join(self._chunks)

    async def stream(self, text: str):
        for c in self._chunks:
            yield c


class _RecordingPublisher:
    def __init__(self):
        self.published = []

    async def publish(self, user_id, event, event_type=None):
        self.published.append((user_id, event, event_type))


async def test_synthesize_and_publish_emits_seqed_audio_chunks():
    """The output-bridge TTS handler turns an AgentResponse into ordered
    AgentAudioChunk events on the publisher."""
    from agentkit.runtime.agents.messaging import Message
    from agentkit.modalities.voice.event_models import AgentResponse
    from agentkit.workers.main import _synthesize_and_publish

    publisher = _RecordingPublisher()
    provider = _FakeProvider([b"aa", b"bb", b"cc"])
    msg = Message(source="t", event=AgentResponse(content="hi", user_id="u1"))

    await _synthesize_and_publish(msg, publisher, provider)

    assert len(publisher.published) == 3
    for i, (uid, event, etype) in enumerate(publisher.published):
        assert uid == "u1"
        assert etype == "agent.audio"
        assert isinstance(event, AgentAudioChunk)
        assert event.seq == i
    # Chunks decode back to the original audio in order.
    assert b"".join(e.to_bytes() for _, e, _ in publisher.published) == b"aabbcc"


async def test_synthesize_and_publish_skips_empty_response():
    from agentkit.runtime.agents.messaging import Message
    from agentkit.modalities.voice.event_models import AgentResponse
    from agentkit.workers.main import _synthesize_and_publish

    publisher = _RecordingPublisher()
    provider = _FakeProvider([b"x"])
    msg = Message(source="t", event=AgentResponse(content="   ", user_id="u1"))

    await _synthesize_and_publish(msg, publisher, provider)
    assert publisher.published == []
