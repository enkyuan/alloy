"""AgentBuilder: fluent builder for AgentRuntime."""
from __future__ import annotations

from typing import Any, List, Optional

from agentkit.infra.events.protocols import EventBusProtocol
from agentkit.infra.events.store import EventStore
from agentkit.runtime.agents.planner import ToolPlanner
from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.runtime.agents.strategy import AgentStrategy
from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.tools.policies import ToolPolicy
from agentkit.runtime.tools.registry import ToolRegistry


class AgentBuilder:
    """Fluent builder for AgentRuntime.

    Registers integrations into a scoped ToolRegistry before constructing
    the runtime so AgentRuntime stays a pure executor.

    Example::

        runtime = (
            AgentBuilder()
            .provider(anthropic_provider)
            .integration(StripeIntegration(api_key=...))
            .policy(ToolPolicy(require_approval_for={"financial"}))
            .system_prompt("You are a payment assistant.")
            .build(bus=bus, store=store)
        )
    """

    def __init__(self) -> None:
        self._provider: Optional[ModelProvider] = None
        self._integrations: List[Any] = []  # List[Integration] — avoid circular import
        self._policy: Optional[ToolPolicy] = None
        self._system_prompt: str = "You are a helpful assistant."
        self._strategy: Optional[AgentStrategy] = None

    def provider(self, p: ModelProvider) -> "AgentBuilder":
        self._provider = p
        return self

    def integration(self, i: Any) -> "AgentBuilder":
        """Add an Integration. Accepts any object with a register(ToolRegistry) method."""
        self._integrations.append(i)
        return self

    def policy(self, p: ToolPolicy) -> "AgentBuilder":
        self._policy = p
        return self

    def system_prompt(self, prompt: str) -> "AgentBuilder":
        self._system_prompt = prompt
        return self

    def strategy(self, s: AgentStrategy) -> "AgentBuilder":
        self._strategy = s
        return self

    def build(self, *, bus: EventBusProtocol, store: EventStore) -> AgentRuntime:
        if self._provider is None:
            raise ValueError("provider() must be called before build()")

        registry = ToolRegistry()
        for integration in self._integrations:
            integration.register(registry)

        # ToolPlanner requires an executor callable, not a registry directly.
        # Wrap registry.execute so the planner can dispatch calls into the
        # scoped registry rather than the global module-level registry.
        async def _executor(tool_name: str, args: dict) -> dict:
            return await registry.execute("builder", tool_name, args)

        # Build a specs mapping so the planner can look up risk per tool.
        specs = {spec.name: spec for spec in registry.list_specs(enabled_only=False)}

        planner = ToolPlanner(
            executor=_executor,
            policy=self._policy,
            specs=specs,
        )

        return AgentRuntime(
            bus=bus,
            store=store,
            provider=self._provider,
            planner=planner,
            system_prompt=self._system_prompt,
            strategy=self._strategy,
            tools=registry.list_specs(),
        )
