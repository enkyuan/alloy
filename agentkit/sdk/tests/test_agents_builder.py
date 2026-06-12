"""Tests for AgentBuilder."""
from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

from agentkit.infra.events.bus import EventBus
from agentkit.infra.events.store import InMemoryEventStore
from agentkit.runtime.agents.builder import AgentBuilder
from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.providers.types import GenerateResponse, ModelResponseChunk
from agentkit.runtime.tools.policies import ToolPolicy
from agentkit.runtime.tools.registry import ToolRegistry, ToolSpec


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------


class _MockProvider(ModelProvider):
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[Any] = None,
    ) -> GenerateResponse:
        return GenerateResponse(text="mock response", tool_calls=[])

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[Any] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        yield ModelResponseChunk(delta="mock response", tool_calls=[])


class _PingIntegration:
    """Minimal integration that registers a single 'ping' tool."""

    def register(self, registry: ToolRegistry) -> None:
        spec = ToolSpec(name="ping", description="Ping", parameters={})

        @registry.register(spec)
        async def ping(ctx, args):  # noqa: ANN001
            return {"pong": True}


def _make_infra():
    bus = EventBus()
    store = InMemoryEventStore()
    return bus, store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_requires_provider():
    """build() must raise ValueError when no provider is set."""
    bus, store = _make_infra()
    with pytest.raises(ValueError, match="provider"):
        AgentBuilder().build(bus=bus, store=store)


@pytest.mark.asyncio
async def test_builder_no_integrations():
    """Builder with just a provider produces an AgentRuntime with no tools."""
    bus, store = _make_infra()
    runtime = AgentBuilder().provider(_MockProvider()).build(bus=bus, store=store)
    assert isinstance(runtime, AgentRuntime)
    assert runtime.tools == []


@pytest.mark.asyncio
async def test_builder_with_integration():
    """Builder with an integration registers the integration's tool on the runtime."""
    bus, store = _make_infra()
    runtime = (
        AgentBuilder()
        .provider(_MockProvider())
        .integration(_PingIntegration())
        .build(bus=bus, store=store)
    )
    assert isinstance(runtime, AgentRuntime)
    tool_names = [spec.name for spec in runtime.tools]
    assert "ping" in tool_names


@pytest.mark.asyncio
async def test_builder_with_policy():
    """Builder with a policy stores it on the planner."""
    bus, store = _make_infra()
    policy = ToolPolicy(require_approval_for={"financial"})
    runtime = (
        AgentBuilder()
        .provider(_MockProvider())
        .policy(policy)
        .build(bus=bus, store=store)
    )
    assert runtime.planner.policy is policy
