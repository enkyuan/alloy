"""AgentBuilder: fluent builder for AgentRuntime."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from kaji.infra.events.protocols import EventJournal
from kaji.infra.events.store import EventStore
from kaji.infra.events.store.inmem import InMemoryEventStore
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
)
from kaji.runtime.agents.coordinator import TurnCoordinator
from kaji.runtime.agents.limits import TurnExecutionLimits
from kaji.runtime.agents.context import ContextWindow, ToolInvocation, TurnContext
from kaji.runtime.agents.approval import ApprovalHandler
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from kaji.runtime.tools.idempotency import ToolIdempotencyLedger
from kaji.core.determinism import Clock, IdFactory, TimerScheduler


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
            .policy(ToolPolicy(require_approval_for={"destructive"}))
            .approval_handler(my_approval_handler)
            .system_prompt("You are a payment assistant.")
            .build(store=store)
        )
    """

    def __init__(self) -> None:
        self._provider: Optional[ModelProvider] = None
        self._integrations: List[Integrable] = []
        self._policy: Optional[ToolPolicy] = None
        self._approval_handler: ApprovalHandler | None = None
        self._system_prompt: str = "You are a helpful assistant."
        self._strategy: Optional[AgentStrategy] = None
        self._coordinator: Optional[TurnCoordinator] = None
        self._context_window: ContextWindow | None = None
        self._default_context: TurnContext | None = None
        self._tool_execution_limits: ToolExecutionLimits | None = None
        self._turn_execution_limits: TurnExecutionLimits | None = None
        self._tool_idempotency_ledger: ToolIdempotencyLedger | None = None
        self._metrics_sink: MetricsSink = NOOP_METRICS
        self._trace_sink: TraceSink = NOOP_TRACE
        self._id_factory: IdFactory | None = None
        self._clock: Clock | None = None
        self._timer_scheduler: TimerScheduler | None = None

    def provider(self, p: ModelProvider) -> "AgentBuilder":
        self._provider = p
        return self

    def integration(self, i: Integrable) -> "AgentBuilder":
        """Add an Integration. Accepts any object with a register(ToolRegistry) method."""
        self._integrations.append(i)
        return self

    def tool(self, bound: Integrable) -> "AgentBuilder":
        """Add a function-level tool created by ``@function_tool``."""
        return self.integration(bound)

    def policy(self, p: ToolPolicy) -> "AgentBuilder":
        self._policy = p
        return self

    def approval_handler(self, handler: ApprovalHandler) -> "AgentBuilder":
        """Set the typed handler used for approval decisions."""
        self._approval_handler = handler
        return self

    def system_prompt(self, prompt: str) -> "AgentBuilder":
        self._system_prompt = prompt
        return self

    def strategy(self, s: AgentStrategy) -> "AgentBuilder":
        self._strategy = s
        return self

    def coordinator(self, coordinator: TurnCoordinator) -> "AgentBuilder":
        """Inject session-turn coordination shared with the built runtime.

        The runtime otherwise uses the process-local coordinator shared by its
        event store object.
        """
        self._coordinator = coordinator
        return self

    def context_window(self, window: ContextWindow) -> "AgentBuilder":
        """Bound provider history without splitting conversational turns."""
        self._context_window = window
        return self

    def default_context(self, context: TurnContext) -> "AgentBuilder":
        """Configure explicit defaults for single-tenant applications."""
        self._default_context = context
        return self

    def tool_execution_limits(self, limits: ToolExecutionLimits) -> "AgentBuilder":
        """Configure runtime-wide tool concurrency and deadline limits."""
        self._tool_execution_limits = limits
        return self

    def turn_execution_limits(self, limits: TurnExecutionLimits) -> "AgentBuilder":
        """Configure the whole-turn deadline and provider response bounds."""
        self._turn_execution_limits = limits
        return self

    def tool_idempotency_ledger(self, ledger: ToolIdempotencyLedger) -> "AgentBuilder":
        """Inject durable or application-scoped exact-call idempotency."""
        self._tool_idempotency_ledger = ledger
        return self

    def metrics_sink(self, sink: MetricsSink) -> "AgentBuilder":
        """Inject a dependency-free recording sink for runtime metrics."""
        self._metrics_sink = sink
        return self

    def trace_sink(self, sink: TraceSink) -> "AgentBuilder":
        """Inject a dependency-free trace sink for runtime spans."""
        self._trace_sink = sink
        return self

    def id_factory(self, factory: IdFactory) -> "AgentBuilder":
        """Inject scoped identifiers for deterministic execution."""
        self._id_factory = factory
        return self

    def clock(self, clock: Clock) -> "AgentBuilder":
        """Inject wall and monotonic time for deterministic execution."""
        self._clock = clock
        return self

    def timer_scheduler(self, scheduler: TimerScheduler) -> "AgentBuilder":
        """Inject deterministic one-shot timers for deadline races."""
        self._timer_scheduler = scheduler
        return self

    def build(
        self,
        *,
        store: Optional[EventStore] = None,
        journal: Optional[EventJournal] = None,
    ) -> AgentRuntime:
        """Build the runtime with a stable in-memory journal by default."""
        if self._provider is None:
            raise ValueError("provider() must be called before build()")
        if store is None:
            store = journal.store if journal is not None else InMemoryEventStore()

        registry = ToolRegistry()
        for integration in self._integrations:
            integration.register(registry)

        async def _executor(invocation: ToolInvocation) -> dict:
            return await registry.execute(invocation)

        # Build a specs mapping so the planner can look up risk per tool.
        specs = {spec.name: spec for spec in registry.list_specs(enabled_only=False)}

        controller = ToolExecutionController(
            limits=self._tool_execution_limits,
            ledger=self._tool_idempotency_ledger,
            metrics_sink=self._metrics_sink,
            trace_sink=self._trace_sink,
            **({"clock": self._clock.now_monotonic} if self._clock else {}),
            **(
                {"timer_scheduler": self._timer_scheduler}
                if self._timer_scheduler
                else {}
            ),
        )
        planner = ToolPlanner(
            executor=_executor,
            policy=self._policy,
            approval_handler=self._approval_handler,
            specs=specs,
            controller=controller,
            id_factory=self._id_factory,
            clock=self._clock,
        )

        return AgentRuntime(
            store=store,
            journal=journal,
            provider=self._provider,
            planner=planner,
            system_prompt=self._system_prompt,
            strategy=self._strategy,
            tools=registry.list_specs(),
            coordinator=self._coordinator,
            context_window=self._context_window,
            default_context=self._default_context,
            tool_execution_controller=controller,
            turn_execution_limits=self._turn_execution_limits,
            metrics_sink=self._metrics_sink,
            trace_sink=self._trace_sink,
            id_factory=self._id_factory,
            clock=self._clock,
            timer_scheduler=self._timer_scheduler,
        )
