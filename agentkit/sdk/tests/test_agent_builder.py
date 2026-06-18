"""Tests for AgentBuilder fluent API, integration wiring, and policy threading."""

from __future__ import annotations

from typing import Any

import pytest

from agentkit.infra.events.bus import InMemoryEventBus
from agentkit.infra.events.schemas import UserMessage
from agentkit.infra.events.store import InMemoryEventStore
from agentkit.infra.events.types import EventType
from agentkit.runtime.agents.builder import AgentBuilder
from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.runtime.tools.policies import ToolPolicy
from agentkit.runtime.tools.registry import ToolContext, ToolRegistry, ToolSpec
from tests.helpers.mock_provider import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class PingIntegration:
    """Minimal integration that registers a 'ping' tool via decorator pattern."""

    def register(self, registry: ToolRegistry) -> None:
        spec = ToolSpec(name="ping", description="Ping", parameters={})

        @registry.register(spec)
        async def _ping(ctx: ToolContext, args: dict) -> dict:
            return {"pong": True}


class MultiIntegration:
    """Integration that registers two tools: alpha and beta."""

    def register(self, registry: ToolRegistry) -> None:
        for name in ("alpha", "beta"):
            spec = ToolSpec(name=name, description=name, parameters={})

            # Use a default arg to capture loop variable
            def _make_handler(tool_name: str) -> Any:
                async def _handler(ctx: ToolContext, args: dict) -> dict:
                    return {"tool": tool_name}
                return _handler

            registry.register(spec)(_make_handler(name))


def _make_infra() -> tuple[InMemoryEventBus, InMemoryEventStore]:
    return InMemoryEventBus(), InMemoryEventStore()


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


def test_builder_requires_provider() -> None:
    bus, store = _make_infra()
    with pytest.raises(ValueError, match="provider"):
        AgentBuilder().build(bus=bus, store=store)


def test_builder_builds_agent_runtime_with_no_integrations() -> None:
    bus, store = _make_infra()
    runtime = AgentBuilder().provider(MockProvider()).build(bus=bus, store=store)
    assert isinstance(runtime, AgentRuntime)


def test_builder_system_prompt_is_applied() -> None:
    bus, store = _make_infra()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .system_prompt("You are a test assistant.")
        .build(bus=bus, store=store)
    )
    assert runtime.prompt.template == "You are a test assistant."


# ---------------------------------------------------------------------------
# Integration tool registration
# ---------------------------------------------------------------------------


def test_builder_registers_integration_tools() -> None:
    bus, store = _make_infra()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .build(bus=bus, store=store)
    )
    tool_names = [spec.name for spec in runtime.tools]
    assert "ping" in tool_names


def test_builder_registers_multiple_integrations() -> None:
    bus, store = _make_infra()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .integration(MultiIntegration())
        .build(bus=bus, store=store)
    )
    tool_names = {spec.name for spec in runtime.tools}
    assert {"ping", "alpha", "beta"}.issubset(tool_names)


# ---------------------------------------------------------------------------
# End-to-end: builder-registered tools are actually executable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_tool_executes_via_scoped_registry() -> None:
    """Integration tools registered via builder run through the scoped registry."""
    bus, store = _make_infra()
    session_id = "s-builder-e2e"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .build(bus=bus, store=store)
    )

    await store.append(UserMessage(session_id=session_id, content="ping please"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_CALL_COMPLETED in types
    completed = next(e for e in events if e.type == EventType.TOOL_CALL_COMPLETED)
    assert completed.result == {"pong": True}


# ---------------------------------------------------------------------------
# Policy wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_deny_policy_blocks_tool() -> None:
    bus, store = _make_infra()
    session_id = "s-builder-deny"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .policy(ToolPolicy(denied={"ping"}))
        .build(bus=bus, store=store)
    )

    await store.append(UserMessage(session_id=session_id, content="ping"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_CALL_FAILED in types
    assert EventType.TOOL_CALL_COMPLETED not in types


@pytest.mark.asyncio
async def test_builder_no_integrations_completes_without_tool_calls() -> None:
    bus, store = _make_infra()
    session_id = "s-builder-no-tools"

    runtime = AgentBuilder().provider(MockProvider()).build(bus=bus, store=store)

    await store.append(UserMessage(session_id=session_id, content="hello"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.AGENT_MESSAGE_COMPLETED in types
    assert EventType.TOOL_CALL_COMPLETED not in types
