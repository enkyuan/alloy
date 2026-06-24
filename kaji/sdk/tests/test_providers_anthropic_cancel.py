"""Symmetric cancellation in AnthropicProvider.

Mirrors the OpenAI/Gemini/Kimi tests: both ``generate()`` and
``generate_stream()`` must raise ``asyncio.CancelledError`` when the
cancellation token is set, so callers observe cancellation uniformly across
providers. The previous ``generate_stream()`` silently ``break``'d
mid-stream, returning a partial response that looked like a clean exit.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.providers.anthropic import AnthropicProvider


def _text_event(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


class _FakeStream:
    """Mimics the ``client.messages.stream(**kwargs)`` async-context object.

    Used via ``async with stream as s: async for event in s``.
    """

    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()


class _FakeMessages:
    def __init__(self, events=None, response=None) -> None:
        self._events = events or []
        self._response = response or SimpleNamespace(
            content=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0)
        )

    async def create(self, **_kw):
        return self._response

    def stream(self, **_kw):
        return _FakeStream(self._events)


class _FakeClient:
    def __init__(self, events=None, response=None) -> None:
        self.messages = _FakeMessages(events=events, response=response)


def _make_provider(events=None, response=None) -> AnthropicProvider:
    with patch("kaji.core.config.settings.ANTHROPIC_API_KEY", "test_key"):
        provider = AnthropicProvider()
    provider._client = _FakeClient(events=events, response=response)
    return provider


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
    provider = _make_provider(events=[_text_event("never")])
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        async for _ in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            pass


async def test_generate_stream_raises_mid_stream_on_cancel():
    """Cancellation observed during streaming raises rather than break-exiting."""
    provider = _make_provider(
        events=[_text_event("hello "), _text_event("world"), _text_event("!")]
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
    provider = _make_provider(events=[_text_event("ok")])
    token = CancellationToken()

    chunks = []
    async for chunk in provider.generate_stream(
        messages=[{"role": "user", "content": "hi"}],
        cancellation_token=token,
    ):
        chunks.append(chunk)

    assert any(c.delta == "ok" for c in chunks)
