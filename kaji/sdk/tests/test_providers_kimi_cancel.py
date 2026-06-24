"""Symmetric cancellation in KimiProvider.

Both ``generate()`` and ``generate_stream()`` must raise CancelledError when
the token is set, so callers can rely on a uniform observation. The previous
``generate_stream()`` silently ``break``'d mid-stream, returning a partial
result that looked like a clean exit; ``generate()`` had no check at all.

Kimi is the default provider, so this is the most user-visible gap of the
three.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.providers.kimi import KimiProvider


def _make_provider() -> KimiProvider:
    with (
        patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"),
        patch("kaji.core.config.settings.CLOUDFLARE_ACCOUNT_ID", None),
    ):
        return KimiProvider()


class _StreamResponse:
    """Fake httpx streaming response that yields canned SSE lines."""

    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):  # pragma: no cover - error path not exercised here
        return b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


class _StreamClient:
    def __init__(self, lines):
        self._lines = lines

    def stream(self, *_args, **_kwargs):
        return _StreamResponse(self._lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


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

    lines = [
        'data: {"choices":[{"delta":{"content":"never"}}]}',
        "data: [DONE]",
    ]

    with patch("httpx.AsyncClient", return_value=_StreamClient(lines)):
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
    provider = _make_provider()
    token = CancellationToken()

    lines = [
        'data: {"choices":[{"delta":{"content":"hello "}}]}',
        'data: {"choices":[{"delta":{"content":"world"}}]}',
        'data: {"choices":[{"delta":{"content":"!"}}]}',
        "data: [DONE]",
    ]

    async def consume():
        chunks = []
        with patch("httpx.AsyncClient", return_value=_StreamClient(lines)):
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
    provider = _make_provider()
    token = CancellationToken()

    lines = [
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        "data: [DONE]",
    ]

    chunks = []
    with patch("httpx.AsyncClient", return_value=_StreamClient(lines)):
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            chunks.append(chunk)

    assert any(c.delta == "ok" for c in chunks)
