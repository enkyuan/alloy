"""Smoke test for the Python minimal_agent example shape.

Asserts that ``function_tool`` + ``AgentBuilder.tool`` + ``runtime.turn``
compose cleanly. Drives the agent loop against ``MockProvider`` so the test
needs no API keys.
"""

from __future__ import annotations

import pytest

from kaji.runtime.agents import AgentBuilder, TurnContext
from kaji.runtime.integrations import function_tool
from kaji.runtime.providers.mock import MockProvider


@function_tool(description="Return weather for a city.", risk="read")
async def get_weather(city: str) -> dict:
    return {"city": city, "tempF": 68}


@pytest.mark.asyncio
async def test_function_tool_runs_through_turn():
    runtime = (
        AgentBuilder()
        .provider(MockProvider(reply="It is 68F in Seattle."))
        .tool(get_weather)
        .default_context(TurnContext(principal_id="quickstart"))
        .system_prompt("You are a weather assistant.")
        .build()
    )
    result = await runtime.turn("What's the weather in Seattle?")
    assert result.text == "It is 68F in Seattle."
    assert result.session_id


@pytest.mark.asyncio
async def test_function_tool_drives_a_tool_call():
    """MockProvider scripts a tool call; loop terminates on the second turn."""
    runtime = (
        AgentBuilder()
        .provider(
            MockProvider(
                tool_call={"name": "fn_get_weather", "args": {"city": "Seattle"}}
            )
        )
        .tool(get_weather)
        .default_context(TurnContext(principal_id="quickstart"))
        .build()
    )
    result = await runtime.turn("What is the weather?")
    # The mock fires one tool call on iteration 1, then terminal text on iteration 2.
    from kaji.infra.events.types import EventType

    assert any(e.type == EventType.TOOL_CALL_REQUESTED for e in result.tool_call_events)
