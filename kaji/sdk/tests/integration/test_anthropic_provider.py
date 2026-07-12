"""Integration smoke test for AnthropicProvider.

Requires ANTHROPIC_API_KEY to be set. Skipped automatically by conftest when
the key is absent.

Run manually:
    ANTHROPIC_API_KEY=sk-ant-... pytest -m integration tests/integration/test_anthropic_provider.py
"""

import os
from typing import Any

import pytest

import kaji
from kaji.infra.events.types import EventType
from kaji.runtime.agents.context import TurnContext


class EchoProbeIntegration(kaji.Integration):
    namespace = "probe"

    @kaji.tool(
        description="Echo the supplied marker back to the caller.",
        parameters={
            "type": "object",
            "properties": {"marker": {"type": "string"}},
            "required": ["marker"],
            "additionalProperties": False,
        },
        risk="read",
    )
    async def echo_probe(
        self, ctx: kaji.ToolContext, args: dict[str, Any]
    ) -> dict[str, Any]:
        return {"marker": args["marker"], "source": "kaji-live-tool-loop"}


@pytest.mark.integration
async def test_anthropic_generate_returns_nonempty_content() -> None:
    """AnthropicProvider.generate() returns a non-empty text response for a simple prompt."""
    assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY must be set"

    from kaji.runtime.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider()
    response = await provider.generate(
        messages=[{"role": "user", "content": "Say hello in one word."}],
        tools=[],
    )

    assert isinstance(response.text, str), "response.text should be a string"
    assert len(response.text.strip()) > 0, "response.text should not be empty"


@pytest.mark.integration
async def test_anthropic_agent_executes_tool_and_finishes() -> None:
    """A real Anthropic call executes a normalized tool and returns final text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    assert api_key, "ANTHROPIC_API_KEY must be set"

    from kaji.runtime.providers.anthropic import AnthropicProvider

    marker = "kaji-anthropic-live-marker"
    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()
    runtime = (
        kaji.AgentBuilder()
        .provider(
            AnthropicProvider(
                api_key=api_key,
                model=os.environ.get("KAJI_LIVE_ANTHROPIC_MODEL"),
            )
        )
        .integration(EchoProbeIntegration())
        .default_context(TurnContext(principal_id="anthropic-live"))
        .system_prompt(
            "You are testing SDK tool execution. You must call the "
            "`probe_echo_probe` tool exactly once with the marker from the "
            "user message before giving a final answer."
        )
        .build(bus=bus, store=store)
    )

    result = await runtime.turn(
        (
            f"Call `probe_echo_probe` with marker `{marker}`. "
            "After the tool returns, answer with the marker value."
        ),
        session_id="anthropic-live-tool-loop",
    )

    requested = [
        event for event in result.events if event.type == EventType.TOOL_CALL_REQUESTED
    ]
    completed = [
        event for event in result.events if event.type == EventType.TOOL_CALL_COMPLETED
    ]
    event_types = [event.type for event in result.events]
    assert len(requested) == 1
    assert len(completed) == 1
    assert requested[0].tool_call_id == completed[0].tool_call_id
    assert EventType.AGENT_MESSAGE_COMPLETED in event_types
    assert EventType.TOOL_CALL_FAILED not in event_types
    assert EventType.AGENT_TURN_EXHAUSTED not in event_types
    assert len(result.tool_call_events) == 1
    assert marker in result.text
