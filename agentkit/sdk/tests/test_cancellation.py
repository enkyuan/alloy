"""Tests for the asyncio-compatible CancellationToken."""

from __future__ import annotations

import asyncio

import pytest

from agentkit.runtime.agents.cancellation import CancellationToken, CancelledError


def test_starts_not_cancelled() -> None:
    token = CancellationToken()
    assert token.is_cancelled is False


def test_cancel_flips_is_cancelled() -> None:
    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True


def test_cancel_is_idempotent() -> None:
    token = CancellationToken()
    token.cancel()
    token.cancel()
    assert token.is_cancelled is True


def test_raise_if_cancelled_is_a_noop_before_cancel() -> None:
    token = CancellationToken()
    token.raise_if_cancelled()  # no exception


def test_raise_if_cancelled_raises_after_cancel() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        token.raise_if_cancelled()


def test_raise_if_cancelled_raises_subclass_of_asyncio_cancelled_error() -> None:
    """Code that catches asyncio.CancelledError uniformly should also
    catch our cancellation, so the standard structured-cancellation
    machinery continues to work."""
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError) as info:
        token.raise_if_cancelled()
    assert isinstance(info.value, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_wait_returns_after_cancel() -> None:
    token = CancellationToken()

    async def cancel_after(delay: float) -> None:
        await asyncio.sleep(delay)
        token.cancel()

    asyncio.create_task(cancel_after(0.01))
    await asyncio.wait_for(token.wait(), timeout=1.0)
    assert token.is_cancelled


@pytest.mark.asyncio
async def test_wait_returns_immediately_if_already_cancelled() -> None:
    token = CancellationToken()
    token.cancel()
    # Should not block.
    await asyncio.wait_for(token.wait(), timeout=0.1)


def test_event_property_exposes_asyncio_event() -> None:
    token = CancellationToken()
    assert isinstance(token.event, asyncio.Event)
    token.cancel()
    assert token.event.is_set()
