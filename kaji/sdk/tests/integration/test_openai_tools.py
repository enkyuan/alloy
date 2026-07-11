"""Live OpenAI agent tool-loop proof.

Requires ``OPENAI_API_KEY``. The model defaults to ``gpt-5.4-mini`` and can be
overridden with ``KAJI_LIVE_OPENAI_MODEL``.

Run manually:
    OPENAI_API_KEY=sk-... pytest -m integration tests/integration/test_openai_tools.py
"""

from __future__ import annotations

import os
from typing import Any

import pytest

import kaji
from kaji.infra.events.types import EventType
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.providers.openai import OpenAIProvider


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
async def test_openai_agent_executes_tool_and_finishes() -> None:
    """The readiness signal: real OpenAI -> SDK tool execution -> final text."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set - skipping integration test")

    marker = "kaji-live-tool-loop-marker"
    model = os.environ.get("KAJI_LIVE_OPENAI_MODEL", "gpt-5.4-mini")

    bus = kaji.InMemoryEventBus()
    store = kaji.InMemoryEventStore()
    runtime = (
        kaji.AgentBuilder()
        .provider(OpenAIProvider(api_key=api_key, model=model))
        .integration(EchoProbeIntegration())
        .default_context(TurnContext(principal_id="openai-live"))
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
        session_id="openai-live-tool-loop",
    )

    types = [event.type for event in result.events]

    requested = [
        event for event in result.events if event.type == EventType.TOOL_CALL_REQUESTED
    ]
    completed_tools = [
        event for event in result.events if event.type == EventType.TOOL_CALL_COMPLETED
    ]

    assert len(requested) == 1, (
        "OpenAI did not request the probe tool. The SDK live-readiness "
        "test requires a real model tool call, not just text generation."
    )
    assert len(completed_tools) == 1, (
        "OpenAI did not complete the probe tool call. The SDK live-readiness "
        "test requires a real model tool call, not just text generation."
    )
    assert requested[0].tool_call_id == completed_tools[0].tool_call_id
    assert EventType.TOOL_CALL_FAILED not in types
    assert EventType.AGENT_TURN_EXHAUSTED not in types, (
        "OpenAI requested tools but the runtime exhausted the tool loop before final text."
    )

    completed = [
        event.content
        for event in result.events
        if event.type == EventType.AGENT_MESSAGE_COMPLETED
    ]
    assert completed, "OpenAI completed the tool call but did not produce final text"
    assert len(result.tool_call_events) == 1
    assert any(marker in content for content in completed), (
        "OpenAI final text did not mention the probe marker returned by the tool"
    )
