"""AgentBuilder: fluent builder for AgentRuntime."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.infra.events.protocols import EventBusProtocol, EventJournal
from kaji.infra.events.store import EventStore
from kaji.infra.events.store.inmem import InMemoryEventStore
from kaji.runtime.agents.planner import ApprovalHandler, ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry


@runtime_checkable
class Integrable(Protocol):
    """Anything with a ``register(registry: ToolRegistry)`` method.

    ``Integration`` subclasses satisfy this, as does ``BoundTool`` from
    ``@function_tool``. Accepting the protocol means ``AgentBuilder`` doesn't
    need to know about either concrete type.
    """

    def register(self, registry: ToolRegistry) -> None: ...


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
            .approval_handler(my_approval_handler)
            .system_prompt("You are a payment assistant.")
            .build(bus=bus, store=store)
        )
    """

    def __init__(self) -> None:
        self._provider: Optional[ModelProvider] = None
        self._integrations: List[Integrable] = []
        self._policy: Optional[ToolPolicy] = None
        self._approval_handler: Optional[ApprovalHandler] = None
        self._system_prompt: str = "You are a helpful assistant."
        self._strategy: Optional[AgentStrategy] = None

    def provider(self, p: ModelProvider) -> "AgentBuilder":
        self._provider = p
        return self

    def integration(self, i: Integrable) -> "AgentBuilder":
        """Add an Integration. Accepts any object with a register(ToolRegistry) method."""
        self._integrations.append(i)
        return self

    def tool(self, bound: Integrable) -> "AgentBuilder":
        """Add a function-level tool created by ``@function_tool``."""
        self._integrations.append(bound)
        return self

    def policy(self, p: ToolPolicy) -> "AgentBuilder":
        self._policy = p
        return self

    def approval_handler(self, handler: ApprovalHandler) -> "AgentBuilder":
        """Set an async approval handler for tools that require explicit approval.

        The handler receives ``(tool_name, tool_args, risk)`` and returns
        ``True`` to allow execution or ``False`` to reject it. When a policy
        marks a tool as requiring approval and no handler is set, the tool is
        rejected by default (fail-safe).
        """
        self._approval_handler = handler
        return self

    def system_prompt(self, prompt: str) -> "AgentBuilder":
        self._system_prompt = prompt
        return self

    def strategy(self, s: AgentStrategy) -> "AgentBuilder":
        self._strategy = s
        return self

    def build(
        self,
        *,
        bus: Optional[EventBusProtocol] = None,
        store: Optional[EventStore] = None,
        journal: Optional[EventJournal] = None,
    ) -> AgentRuntime:
        """Build the runtime with a stable in-memory journal by default.

        Passing ``bus`` opts into the experimental split store/bus adapter.
        """
        if self._provider is None:
            raise ValueError("provider() must be called before build()")
        if journal is not None:
            if store is not None and store is not journal.store:
                raise ValueError("store must be the same object as journal.store")
            store = journal.store
        else:
            if store is None:
                store = InMemoryEventStore()
            journal = (
                SplitEventJournal(store, bus)
                if bus is not None
                else InMemoryEventJournal(store)
            )

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
            approval_handler=self._approval_handler,
            specs=specs,
        )

        return AgentRuntime(
            bus=bus,
            store=store,
            journal=journal,
            provider=self._provider,
            planner=planner,
            system_prompt=self._system_prompt,
            strategy=self._strategy,
            tools=registry.list_specs(),
        )
