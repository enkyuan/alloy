"""Streaming parity tests for GeminiProvider (#6).

Gemini streaming must pass full message history and surface tool calls, like
the non-streaming generate(). These tests inject a fake GeminiService so no API
key or network is needed.
"""

from types import SimpleNamespace

import pytest

from kaji.runtime.providers.types import ModelResponseChunk


def _text_chunk(text):
    """A stream chunk that yields text and no function calls."""
    return SimpleNamespace(text=text, candidates=[])


def _tool_chunk(name, args):
    """A stream chunk whose part is a function call (and whose .text raises)."""
    function_call = SimpleNamespace(name=name, args=args)
    part = SimpleNamespace(function_call=function_call)
    content = SimpleNamespace(parts=[part])
    candidate = SimpleNamespace(content=content)

    class _Chunk:
        candidates = [candidate]

        @property
        def text(self):  # mirrors the real SDK raising on non-text parts
            raise ValueError("no text in a function-call chunk")

    return _Chunk()


class FakeGeminiService:
    """Captures the stream call and replays canned chunks."""

    model = "gemini-test"

    def __init__(self, chunks):
        self._chunks = chunks
        self.captured = {}
        self.generate_captured = {}

    async def generate_chat_response(
        self,
        messages,
        system_instruction=None,
        temperature=0.7,
        tools=None,
        max_tokens=None,
    ):
        self.generate_captured = {
            "messages": messages,
            "system_instruction": system_instruction,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        return SimpleNamespace(text="ok", candidates=[], usage_metadata=None)

    async def generate_chat_stream(
        self,
        messages,
        system_instruction=None,
        temperature=0.7,
        tools=None,
        max_tokens=None,
    ):
        self.captured = {
            "messages": messages,
            "system_instruction": system_instruction,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        for chunk in self._chunks:
            yield chunk


def _provider_with(service):
    from kaji.runtime.providers.gemini import GeminiProvider

    return GeminiProvider(service=service)


@pytest.mark.asyncio
async def test_stream_yields_text_deltas():
    service = FakeGeminiService([_text_chunk("Hello"), _text_chunk(" World")])
    provider = _provider_with(service)

    deltas = []
    async for chunk in provider.generate_stream(
        messages=[{"role": "user", "content": "hi"}]
    ):
        assert isinstance(chunk, ModelResponseChunk)
        deltas.append(chunk.delta)

    assert deltas == ["Hello", " World"]


@pytest.mark.asyncio
async def test_generate_forwards_output_limit_to_service():
    service = FakeGeminiService([])
    provider = _provider_with(service)

    response = await provider.generate(
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=123,
    )

    assert response.text == "ok"
    assert service.generate_captured["max_tokens"] == 123


@pytest.mark.asyncio
async def test_stream_passes_full_history_and_translates_tools():
    service = FakeGeminiService([_text_chunk("ok")])
    provider = _provider_with(service)

    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    neutral_tools = [
        {"name": "lookup", "description": "d", "parameters": {"type": "object"}}
    ]

    async for _ in provider.generate_stream(
        messages=history,
        tools=neutral_tools,
        system_instruction="be brief",
        max_tokens=321,
    ):
        pass

    # Full history reached the service (not just the last message).
    assert service.captured["messages"] == history
    assert service.captured["system_instruction"] == "be brief"
    assert service.captured["max_tokens"] == 321
    # Tools were translated to Gemini's function_declarations form.
    assert service.captured["tools"] == [{"function_declarations": neutral_tools}]


@pytest.mark.asyncio
async def test_stream_surfaces_tool_calls():
    service = FakeGeminiService(
        [_text_chunk("thinking"), _tool_chunk("lookup", {"q": "x"})]
    )
    provider = _provider_with(service)

    collected = []
    async for chunk in provider.generate_stream(
        messages=[{"role": "user", "content": "hi"}]
    ):
        collected.append(chunk)

    # First chunk is the text delta; second carries the tool call.
    assert collected[0].delta == "thinking"
    assert collected[0].tool_calls == []

    assert collected[1].delta == ""
    assert len(collected[1].tool_calls) == 1
    call = collected[1].tool_calls[0]
    assert call["name"] == "lookup"
    assert call["arguments"] == {"q": "x"}
    assert "id" in call


@pytest.mark.asyncio
async def test_stream_respects_cancellation():
    """A pre-cancelled token must raise CancelledError, not silently exit.

    The previous silent ``break`` returned an empty list which was
    indistinguishable from a clean end-of-stream; callers now get a
    CancelledError so cancellation is observable.
    """
    import asyncio

    class Token:
        is_cancelled = True

    service = FakeGeminiService([_text_chunk("never")])
    provider = _provider_with(service)

    with pytest.raises(asyncio.CancelledError):
        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}], cancellation_token=Token()
        ):
            pass
