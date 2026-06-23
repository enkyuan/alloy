"""Symmetric cancellation in OpenAIProvider.

Both ``generate()`` and ``generate_stream()`` must raise CancelledError when
the token is set, so callers can rely on a uniform observation. The previous
``generate_stream()`` silently ``break``'d mid-stream, returning a partial
result that looked like a clean exit.
"""

from __future__ import annotations

import asyncio
import pytest

from agentkit.runtime.agents.cancellation import CancellationToken
from agentkit.runtime.providers.openai import OpenAIProvider


def _make_provider() -> OpenAIProvider:
    return OpenAIProvider(model="gpt-4o-mini", api_key="dummy")


async def test_generate_raises_when_token_already_cancelled():
    provider = _make_provider()
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await provider.generate(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        )


async def test_generate_stream_raises_when_token_already_cancelled():
    provider = _make_provider()
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            pass


async def test_generate_stream_raises_mid_stream_on_cancel():
    """Cancellation observed during streaming raises rather than break-exiting.

    Substitutes a fake async iterator for the OpenAI client so we don't need
    a network call. The token is cancelled after the first chunk; the
    generator must raise CancelledError on the next iteration rather than
    silently producing a partial response.
    """

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [
                type("C", (), {"delta": type("D", (), {"content": content, "tool_calls": None})})()
            ]

    async def _fake_stream():
        yield _Chunk("hello ")
        yield _Chunk("world")
        yield _Chunk("!")

    class _FakeCompletions:
        async def create(self, **_kw):
            return _fake_stream()

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self) -> None:
            self.chat = _FakeChat()

    provider = _make_provider()
    # Short-circuit the lazy `client` property: it constructs the real
    # AsyncOpenAI only when `_client is None`. Assigning bypasses the
    # network path without needing a live API key.
    provider._client = _FakeClient()
    token = CancellationToken()

    async def consume():
        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            chunks.append(chunk)
            token.cancel()
        return chunks

    with pytest.raises(asyncio.CancelledError):
        await consume()


async def test_generate_stream_completes_when_token_never_set():
    """Sanity: with no cancellation, the generator drains normally."""

    class _Chunk:
        def __init__(self, content: str) -> None:
            self.choices = [
                type("C", (), {"delta": type("D", (), {"content": content, "tool_calls": None})})()
            ]

    async def _fake_stream():
        yield _Chunk("ok")

    class _FakeCompletions:
        async def create(self, **_kw):
            return _fake_stream()

    class _FakeChat:
        def __init__(self) -> None:
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self) -> None:
            self.chat = _FakeChat()

    provider = _make_provider()
    # Short-circuit the lazy `client` property: it constructs the real
    # AsyncOpenAI only when `_client is None`. Assigning bypasses the
    # network path without needing a live API key.
    provider._client = _FakeClient()
    token = CancellationToken()

    chunks = []
    async for chunk in provider.generate_stream(
        messages=[{"role": "user", "content": "hi"}],
        cancellation_token=token,
    ):
        chunks.append(chunk)

    assert any(c.delta == "ok" for c in chunks)
