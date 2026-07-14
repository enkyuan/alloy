"""Tests for AgentBuilder fluent API, integration wiring, and policy threading."""

from __future__ import annotations

from typing import Any

import pytest

from kaji.infra.events.schemas import UserMessage
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents.approval import ApprovalDecision
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.context import ToolExecutionContext, TurnContext
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec
from tests.helpers.approval import StaticApprovalHandler
from tests.helpers.mock_provider import MockProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class PingIntegration:
    """Minimal integration that registers a 'ping' tool via decorator pattern."""

    def register(self, registry: ToolRegistry) -> None:
        spec = ToolSpec(name="ping", description="Ping", parameters={}, risk="read")

        @registry.register(spec)
        async def _ping(ctx: ToolExecutionContext, args: dict) -> dict:
            return {"pong": True}


class MultiIntegration:
    """Integration that registers two tools: alpha and beta."""

    def register(self, registry: ToolRegistry) -> None:
        for name in ("alpha", "beta"):
            spec = ToolSpec(name=name, description=name, parameters={}, risk="read")

            # Use a default arg to capture loop variable
            def _make_handler(tool_name: str) -> Any:
                async def _handler(ctx: ToolExecutionContext, args: dict) -> dict:
                    return {"tool": tool_name}

                return _handler

            registry.register(spec)(_make_handler(name))


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------


def test_builder_requires_provider() -> None:
    store = InMemoryEventStore()
    with pytest.raises(ValueError, match="provider"):
        AgentBuilder().build(store=store)


def test_builder_builds_agent_runtime_with_no_integrations() -> None:
    store = InMemoryEventStore()
    runtime = AgentBuilder().provider(MockProvider()).build(store=store)
    assert isinstance(runtime, AgentRuntime)


def test_builder_system_prompt_is_applied() -> None:
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .system_prompt("You are a test assistant.")
        .build(store=store)
    )
    assert runtime.prompt.template == "You are a test assistant."


# ---------------------------------------------------------------------------
# Integration tool registration
# ---------------------------------------------------------------------------


def test_builder_registers_integration_tools() -> None:
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .default_context(TurnContext(principal_id="test"))
        .build(store=store)
    )
    tool_names = [spec.name for spec in runtime.tools]
    assert "ping" in tool_names


def test_builder_registers_multiple_integrations() -> None:
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .integration(MultiIntegration())
        .build(store=store)
    )
    tool_names = {spec.name for spec in runtime.tools}
    assert {"ping", "alpha", "beta"}.issubset(tool_names)


# ---------------------------------------------------------------------------
# End-to-end: builder-registered tools are actually executable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_tool_executes_via_scoped_registry() -> None:
    """Integration tools registered via builder run through the scoped registry."""
    store = InMemoryEventStore()
    session_id = "s-builder-e2e"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .default_context(TurnContext(principal_id="test"))
        .build(store=store)
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
    store = InMemoryEventStore()
    session_id = "s-builder-deny"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .default_context(TurnContext(principal_id="test"))
        .policy(ToolPolicy(denied={"ping"}))
        .build(store=store)
    )

    await store.append(UserMessage(session_id=session_id, content="ping"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_CALL_FAILED in types
    assert EventType.TOOL_CALL_COMPLETED not in types


@pytest.mark.asyncio
async def test_builder_no_integrations_completes_without_tool_calls() -> None:
    store = InMemoryEventStore()
    session_id = "s-builder-no-tools"

    runtime = AgentBuilder().provider(MockProvider()).build(store=store)

    await store.append(UserMessage(session_id=session_id, content="hello"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.AGENT_MESSAGE_COMPLETED in types
    assert EventType.TOOL_CALL_COMPLETED not in types


# ---------------------------------------------------------------------------
# Approval handler wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_approval_handler_approves_tool() -> None:
    """A typed approval decision allows the tool to execute and complete."""
    store = InMemoryEventStore()
    session_id = "s-builder-approval-approved"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .default_context(TurnContext(principal_id="test"))
        .policy(ToolPolicy(require_approval_for={"read"}))
        .approval_handler(StaticApprovalHandler(ApprovalDecision(True, "approved")))
        .build(store=store)
    )

    await store.append(UserMessage(session_id=session_id, content="ping"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_APPROVAL_APPROVED in types
    assert EventType.TOOL_CALL_COMPLETED in types


@pytest.mark.asyncio
async def test_builder_approval_handler_rejection_is_terminal() -> None:
    """Rejected approval emits TOOL_CALL_FAILED so replay sees it and the loop stops."""
    store = InMemoryEventStore()
    session_id = "s-builder-approval-rejected"

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PingIntegration())
        .default_context(TurnContext(principal_id="test"))
        .policy(ToolPolicy(require_approval_for={"read"}))
        .approval_handler(
            StaticApprovalHandler(
                ApprovalDecision(False, "rejected", "Rejected by test")
            )
        )
        .build(store=store)
    )

    await store.append(UserMessage(session_id=session_id, content="ping"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_APPROVAL_REJECTED in types
    assert EventType.TOOL_CALL_FAILED in types
    assert EventType.TOOL_CALL_COMPLETED not in types


# ---------------------------------------------------------------------------
# Optional default planner on AgentRuntime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_without_explicit_planner_completes_turn() -> None:
    """AgentRuntime can be constructed without an explicit planner."""
    from kaji.runtime.agents.runtime import AgentRuntime
    from kaji.runtime.tools.registry import ToolSpec, clear_tools, register_tool

    clear_tools()
    spec = ToolSpec(
        name="noop", description="Does nothing.", parameters={}, risk="read"
    )

    @register_tool(spec)
    async def _noop(ctx, args: dict) -> dict:
        return {}

    store = InMemoryEventStore()
    session_id = "s-runtime-no-planner"

    # Construct without planner — should build one from global registry
    from kaji.runtime.tools.registry import list_tool_specs

    runtime = AgentRuntime(
        bus=None,
        store=store,
        provider=MockProvider(),
        tools=list_tool_specs(),
        default_context=TurnContext(principal_id="test"),
    )

    await store.append(UserMessage(session_id=session_id, content="go"))
    await runtime.run_turn(session_id)

    events = await store.get_events(session_id)
    types = [e.type for e in events]

    assert EventType.TOOL_CALL_COMPLETED in types
    clear_tools()
