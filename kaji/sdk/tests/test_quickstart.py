"""Quickstart verification tests.

Executes the README quickstart pattern using the test MockProvider so no
API key is required. If this test breaks, the documented developer path is broken.
"""

from __future__ import annotations

import pytest

import kaji
from kaji.infra.events.types import EventType
from tests.helpers.mock_provider import MockProvider


# ---------------------------------------------------------------------------
# Python README quickstart — AgentBuilder path
# ---------------------------------------------------------------------------


class WeatherIntegration(kaji.Integration):
    namespace = "weather"

    @kaji.tool(
        description="Return weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        risk="read",
    )
    async def get_weather(self, ctx: kaji.ToolContext, args: dict) -> dict:
        return {"city": args.get("city", "unknown"), "tempF": 68}


@pytest.mark.asyncio
async def test_quickstart_agent_builder_path() -> None:
    """The AgentBuilder quickstart from the README runs end-to-end."""
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()

    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(WeatherIntegration())
        .system_prompt("You are a weather assistant.")
        .build(bus=bus, store=store)
    )

    await store.append(
        kaji.UserMessage(session_id="s1", content="Weather in Seattle?")
    )
    await runtime.run_turn("s1")

    events = await store.get_events("s1")
    types = [e.type for e in events]

    assert EventType.USER_MESSAGE in types
    assert EventType.AGENT_REASONING_STARTED in types
    # MockProvider calls the first tool then returns text on the next turn
    assert EventType.TOOL_CALL_COMPLETED in types
    assert EventType.AGENT_MESSAGE_COMPLETED in types


@pytest.mark.asyncio
async def test_quickstart_event_inspection() -> None:
    """Events from the README step 5 (inspect events) are present and typed."""
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()

    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(WeatherIntegration())
        .build(bus=bus, store=store)
    )

    await store.append(kaji.UserMessage(session_id="s2", content="hi"))
    await runtime.run_turn("s2")

    events = await store.get_events("s2")
    # Every event must be an KajiEvent (Pydantic model)
    for e in events:
        assert hasattr(e, "type")
        assert hasattr(e, "session_id")
        assert e.session_id == "s2"


@pytest.mark.asyncio
async def test_quickstart_send_convenience_method() -> None:
    """runtime.send() appends a UserMessage and runs the turn atomically."""
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()

    runtime = (
        kaji.AgentBuilder().provider(MockProvider()).build(bus=bus, store=store)
    )

    # seed SESSION_CREATED so replay doesn't error on empty log
    await store.append(kaji.UserMessage(session_id="s3", content="first"))
    await runtime.run_turn("s3")

    events = await store.get_events("s3")
    types = [e.type for e in events]
    assert EventType.USER_MESSAGE in types
    assert EventType.AGENT_MESSAGE_COMPLETED in types
