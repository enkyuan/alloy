"""Tests for AgentRuntime.turn — the one-call hello-world wrapper."""

from __future__ import annotations

import pytest

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents import AgentBuilder
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.mock import MockProvider


def _build(provider: ModelProvider, store: InMemoryEventStore | None = None):
    bus = InMemoryEventBus()
    store = store or InMemoryEventStore()
    return (
        AgentBuilder().provider(provider).build(bus=bus, store=store),
        store,
    )


@pytest.mark.asyncio
async def test_turn_returns_text_for_simple_reply():
    runtime, _ = _build(MockProvider(reply="hello world"))
    result = await runtime.turn("ping")
    assert result.text == "hello world"
    assert result.session_id
    assert result.tool_call_events == []


@pytest.mark.asyncio
async def test_turn_generates_session_id_when_none_given():
    runtime, store = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first")
    r2 = await runtime.turn("second")
    assert r1.session_id != r2.session_id
    s1 = await store.get_events(r1.session_id)
    s2 = await store.get_events(r2.session_id)
    assert s1 and s2
    assert s1[0].type == EventType.SESSION_CREATED
    assert s2[0].type == EventType.SESSION_CREATED


@pytest.mark.asyncio
async def test_turn_reuses_existing_session_id():
    runtime, store = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first", session_id="s-1")
    r2 = await runtime.turn("second", session_id="s-1")
    assert r1.session_id == r2.session_id == "s-1"
    events = await store.get_events("s-1")
    created = [e for e in events if e.type == EventType.SESSION_CREATED]
    assert len(created) == 1


@pytest.mark.asyncio
async def test_turn_emits_tool_call_requested_event():
    # mock fires one call, then falls through to terminal text on second turn.
    runtime, _ = _build(MockProvider(tool_call={"name": "ping", "args": {}}))
    result = await runtime.turn("call ping")
    assert any(e.type == EventType.TOOL_CALL_REQUESTED for e in result.tool_call_events)


@pytest.mark.asyncio
async def test_turn_text_uses_message_completed_not_delta():
    """Text is sourced from AgentMessageCompleted, not delta accumulation."""
    runtime, _ = _build(MockProvider(reply="exact text"))
    result = await runtime.turn("hi")
    assert result.text == "exact text"


@pytest.mark.asyncio
async def test_turn_returns_events_scoped_to_this_turn():
    runtime, _ = _build(MockProvider(reply="ok"))
    r1 = await runtime.turn("first", session_id="s-1")
    r2 = await runtime.turn("second", session_id="s-1")
    # r2.events should not contain the SessionCreated event (only first turn)
    assert not any(e.type == EventType.SESSION_CREATED for e in r2.events)
    # but r1.events should
    assert any(e.type == EventType.SESSION_CREATED for e in r1.events)


@pytest.mark.asyncio
async def test_turn_propagates_provider_errors():
    """turn() is a wrapper, not an error sink. send() exceptions bubble."""

    class FailingProvider:
        async def generate(self, *_a, **_kw):
            raise RuntimeError("provider boom")

        async def generate_stream(self, *_a, **_kw):
            raise RuntimeError("provider boom")
            yield  # pragma: no cover

    runtime, _ = _build(FailingProvider())
    with pytest.raises(RuntimeError, match="provider boom"):
        await runtime.turn("hi")
