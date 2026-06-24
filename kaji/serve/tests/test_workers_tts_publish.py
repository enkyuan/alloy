"""Tests for the bus-worker TTS output handler (_synthesize_and_publish)."""

from kaji.modalities.voice.event_models import AgentAudioChunk


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
    from kaji_serve.runtime.messaging import Message
    from kaji.modalities.voice.event_models import AgentResponse
    from kaji_serve.workers.main import _synthesize_and_publish

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
    from kaji_serve.runtime.messaging import Message
    from kaji.modalities.voice.event_models import AgentResponse
    from kaji_serve.workers.main import _synthesize_and_publish

    publisher = _RecordingPublisher()
    provider = _FakeProvider([b"x"])
    msg = Message(source="t", event=AgentResponse(content="   ", user_id="u1"))

    await _synthesize_and_publish(msg, publisher, provider)
    assert publisher.published == []
