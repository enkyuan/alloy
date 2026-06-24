"""Symmetric cancellation in GeminiProvider.

Both ``generate()`` and ``generate_stream()`` must raise CancelledError when
the token is set, so callers can rely on a uniform observation. The previous
``generate_stream()`` silently ``break``'d mid-stream, returning a partial
result that looked like a clean exit; ``generate()`` had no check at all.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kaji.runtime.agents.cancellation import CancellationToken


def _text_chunk(text: str):
    return SimpleNamespace(text=text, candidates=[])


class _FakeService:
    """Captures calls and replays canned chunks/response."""

    model = "gemini-test"

    def __init__(self, chunks=None, response=None) -> None:
        self._chunks = chunks or []
        self._response = response or SimpleNamespace(
            text="ok", candidates=[], usage_metadata=None
        )

    async def generate_chat_response(
        self, messages, system_instruction=None, temperature=0.7, tools=None
    ):
        return self._response

    async def generate_chat_stream(
        self, messages, system_instruction=None, temperature=0.7, tools=None
    ):
        for chunk in self._chunks:
            yield chunk


def _make_provider(service):
    with patch(
        "kaji.runtime.providers.gemini.get_gemini_service", return_value=service
    ):
        from kaji.runtime.providers.gemini import GeminiProvider

        return GeminiProvider()


async def test_generate_raises_when_token_already_cancelled():
    provider = _make_provider(_FakeService())
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await provider.generate(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        )


async def test_generate_stream_raises_when_token_already_cancelled():
    provider = _make_provider(_FakeService(chunks=[_text_chunk("never")]))
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

    The token is cancelled after the first chunk; the generator must raise
    CancelledError on the next iteration rather than silently producing a
    partial response.
    """
    provider = _make_provider(
        _FakeService(
            chunks=[_text_chunk("hello "), _text_chunk("world"), _text_chunk("!")]
        )
    )
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
    provider = _make_provider(_FakeService(chunks=[_text_chunk("ok")]))
    token = CancellationToken()

    chunks = []
    async for chunk in provider.generate_stream(
        messages=[{"role": "user", "content": "hi"}],
        cancellation_token=token,
    ):
        chunks.append(chunk)

    assert any(c.delta == "ok" for c in chunks)
