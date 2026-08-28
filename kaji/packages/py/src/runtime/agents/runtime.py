import asyncio
import logging
import math
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, cast

from kaji.core.safe_logging import log_redacted_failure
from kaji.runtime.agents.cancellation import CancellationToken, ProviderDeadlineScope
from kaji.runtime.agents.coordinator import (
    TurnCoordinator,
    TurnLease,
    default_coordinator_for_store,
)
from kaji.runtime.agents.limits import (
    ProviderCancellationContractViolation,
    TurnExecutionLimits,
    TurnTimeoutError,
)
from kaji.runtime.agents.context import (
    ContextDiagnostics,
    ContextWindow,
    MissingToolIdentityError,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.approval import ApprovalHandler
from kaji.runtime.agents.planner import ToolExecutor, ToolPlanner
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.agents.stream import RuntimeStreamAccumulator, StreamDiagnostics
from kaji.runtime.tools.registry import ToolSpec
from kaji.infra.events.errors import (
    SessionPurgeBusyError,
    SessionPurgeComponent,
    SessionPurgeUnsupportedError,
)
from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.protocols import EventJournal
from kaji.infra.events.session_lifecycle import (
    SessionPurgeAuthorization,
    StoreSessionPurgeLease,
    finish_session_cleanup,
    register_runtime_owner,
    retain_store_session_quarantine,
    store_session_operation,
    store_session_purge,
    supports_coordinated_session_purge,
)
from kaji.infra.events.schemas import (
    NewKajiEvent,
    StoredKajiEvent,
    AgentMessageCompleted,
    AgentMessageDelta,
    AgentReasoningStarted,
    AgentTurnExhausted,
    AgentTurnFailed,
    CancellationCompleted,
    EventTokenUsage,
    SessionCreated,
    UserMessage,
    event_defaults,
    require_stored_event,
    revalidate_stored_event,
)
from kaji.infra.events.store import EventStore
from kaji.infra.events.types import EventType
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceAttributeName,
    TraceSink,
    provider_family,
    record_metric,
    span_end,
    span_record_error,
    start_span,
)
from kaji.runtime.providers.base import (
    ModelProvider,
    ProviderDiagnosticsSink,
    provider_diagnostics_scope,
)
from kaji.runtime.providers.errors import ProviderOutputLimitError
from kaji.runtime.providers.types import ProviderResponseLimits, TokenMetrics
from kaji.runtime.sessions.context_index import ContextIndexStats
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from kaji.runtime.tools.idempotency import ToolIdempotencyLedger
from kaji.core.determinism import (
    Clock,
    IdFactory,
    SYSTEM_CLOCK,
    SYSTEM_ID_FACTORY,
    SYSTEM_TIMER_SCHEDULER,
    TimerScheduler,
)


@dataclass(frozen=True)
class TurnResult:
    """The user-facing result of a single ``AgentRuntime.turn`` call.

    Attributes:
        text: All ``AgentMessageCompleted`` content emitted this turn, joined.
            May be empty when the provider returned only tool calls; inspect
            ``events`` for ``AgentTurnExhausted`` when max iterations are hit.
        tool_call_events: ``ToolCallRequested`` events emitted this turn.
            Named for the type honestly (not provider-neutral ``ToolCall``s).
        session_id: The session this turn ran against (auto-generated when
            no ``session_id`` was passed to ``turn``).
        turn_id: The unique identifier shared by every event emitted by this
            turn.
        events: Every event the runtime appended to the store this turn.
    """

    text: str
    session_id: str
    turn_id: str
    tool_call_events: List[StoredKajiEvent] = field(default_factory=list)
    events: List[StoredKajiEvent] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EffectiveRuntimeLimits:
    """Resolved runtime limits used by this agent instance."""

    max_tool_iterations: int
    context_window_turns: int | None
    context_window_characters: int | None
    tool_max_parallel: int
    tool_timeout_seconds: float
    approval_timeout_seconds: float
    turn_timeout_seconds: float
    provider_cancellation_grace_seconds: float
    provider_text_max_bytes: int
    provider_tool_arguments_max_bytes: int
    provider_response_max_bytes: int
    provider_tool_calls_max: int


logger = logging.getLogger(__name__)

_PUBLIC_TURN_FAILURE = "Agent turn failed"
_PUBLIC_TURN_TIMEOUT = "Agent turn timed out"


def _copy_stored_event(event: StoredKajiEvent) -> StoredKajiEvent:
    return require_stored_event(event.model_copy(deep=True))


@dataclass(slots=True)
class _TurnEventCollector:
    session_id: str
    turn_id: str
    cursor: int
    events: list[StoredKajiEvent] = field(default_factory=list)


@dataclass(slots=True)
class _ProviderQuarantine:
    session_id: str
    lease: TurnLease
    settlement: asyncio.Task[None]
    release_lifecycle: Callable[[], None]


class _TurnEventEmitter:
    """One runtime-owned append/observe boundary for a single turn."""

    def __init__(self, runtime: "AgentRuntime", turn_id: str) -> None:
        self._runtime = runtime
        self._turn_id = turn_id
        self.journal = runtime.journal

    async def __call__(self, event: NewKajiEvent) -> StoredKajiEvent:
        return await self._runtime._emit_for_turn(event, self._turn_id)

    async def observe_stored(self, event: StoredKajiEvent) -> None:
        await self._runtime._observe_stored_event(event)


class AgentRuntime:
    """A generic, provider-agnostic agent runtime.

    Consumes Kaji events, maintains session state, calls an abstract ModelProvider,
    executes tool batches via ToolPlanner.

    ``planner`` is optional. When omitted, a default ``ToolPlanner`` is
    constructed from ``tool_executor`` (falls back to the global
    ``execute_tool`` registry), ``policy``, and ``approval_handler``, the same
    lazy-build pattern as the TypeScript ``AgentRuntime``. Pass an explicit
    ``planner`` (e.g. from ``AgentBuilder``) to use a scoped registry instead.

    Without an injected coordinator, runtimes sharing the same ``store``
    object share one process-local coordinator. Different stores remain
    independent; multi-process hosts must inject distributed coordination.
    """

    def __init__(
        self,
        store: EventStore,
        provider: ModelProvider,
        planner: Optional[ToolPlanner] = None,
        system_prompt: str = "You are a helpful assistant.",
        strategy: Optional[AgentStrategy] = None,
        tools: Optional[List[ToolSpec]] = None,
        rag: Optional[Any] = None,
        rag_top_k: int = 5,
        # Optional wiring for the default planner (ignored when planner is given)
        tool_executor: Optional[ToolExecutor] = None,
        policy: Optional[Any] = None,
        approval_handler: ApprovalHandler | None = None,
        journal: Optional[EventJournal] = None,
        coordinator: Optional[TurnCoordinator] = None,
        context_window: ContextWindow | None = None,
        default_context: TurnContext | None = None,
        tool_execution_controller: ToolExecutionController | None = None,
        tool_execution_limits: ToolExecutionLimits | None = None,
        turn_execution_limits: TurnExecutionLimits | None = None,
        tool_idempotency_ledger: ToolIdempotencyLedger | None = None,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        timer_scheduler: TimerScheduler | None = None,
    ):
        resolved_journal: EventJournal = journal or InMemoryEventJournal(
            store, metrics_sink=metrics_sink
        )
        if resolved_journal.store is not store:
            raise ValueError("store must be the same object as journal.store")
        self.store = store
        self.journal = resolved_journal
        self.coordinator = (
            coordinator
            if coordinator is not None
            else default_coordinator_for_store(store)
        )
        self.provider = provider
        self._metrics = metrics_sink
        self._trace = trace_sink
        self._id_factory = id_factory or SYSTEM_ID_FACTORY
        self._clock_source = SYSTEM_CLOCK if clock is None else clock
        self._timer_scheduler = timer_scheduler or SYSTEM_TIMER_SCHEDULER
        self._default_context = default_context
        self.turn_limits = turn_execution_limits or TurnExecutionLimits()
        self._provider_response_limits = ProviderResponseLimits(
            text_max_bytes=self.turn_limits.provider_text_max_bytes,
            tool_arguments_max_bytes=self.turn_limits.provider_tool_arguments_max_bytes,
            response_max_bytes=self.turn_limits.provider_response_max_bytes,
            tool_calls_max=self.turn_limits.provider_tool_calls_max,
        )
        self.prompt = SystemPrompt(system_prompt)
        self.strategy = strategy or AgentStrategy()
        resolved_context_window = context_window or ContextWindow()
        self.context_window = ContextWindow(
            max_turns=resolved_context_window.max_turns,
            max_characters=resolved_context_window.max_characters,
        )
        store_capacity = getattr(store, "max_sessions", 1_000)
        self._projection_cache_capacity = (
            store_capacity
            if isinstance(store_capacity, int) and store_capacity > 0
            else 1_000
        )
        self._projectors: OrderedDict[str, SessionProjector] = OrderedDict()
        self._projection_locks: dict[str, asyncio.Lock] = {}
        self._active_projection_sessions: dict[str, int] = {}
        self._turn_event_collectors: dict[str, _TurnEventCollector] = {}
        self._context_diagnostics: dict[str, ContextDiagnostics] = {}
        self._stream_diagnostics: dict[str, StreamDiagnostics] = {}
        self._provider_quarantine: dict[str, _ProviderQuarantine] = {}
        self._closed = False
        # Tools surfaced to the provider each turn. Empty by default, so a
        # no-tool agent still runs. Pass ``list_tool_specs()`` for the whole
        # registry, or a curated subset (e.g. from a ToolRetriever).
        self.tools = tools or []
        # Provider-neutral tool payload (name/description/parameters). Built
        # once because ``self.tools`` is set at construction time and never
        # mutated; each provider translates this at its boundary.
        self._tool_payload: List[Dict[str, Any]] = [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in self.tools
        ]
        # Optional DocumentRAG instance. When set, the last user message is used
        # to retrieve relevant chunks which are prepended to the system prompt.
        self._rag = rag
        self._rag_top_k = rag_top_k
        # Single source of truth: an explicit planner wins; otherwise we build
        # one from tool_executor / policy / approval_handler. Plain attribute
        # so callers can swap it post-construction (tests do this).
        if planner is not None:
            if tool_execution_limits is not None or tool_idempotency_ledger is not None:
                raise ValueError(
                    "explicit planner cannot be combined with tool execution limits or ledger"
                )
            if (
                tool_execution_controller is not None
                and planner.controller is not tool_execution_controller
            ):
                raise ValueError(
                    "explicit planner and runtime must share the same tool controller"
                )
            self.tool_execution_controller = planner.controller
            self.planner = planner
        else:
            if tool_execution_controller is not None and (
                tool_execution_limits is not None or tool_idempotency_ledger is not None
            ):
                raise ValueError(
                    "tool_execution_controller cannot be combined with limits or ledger"
                )
            self.tool_execution_controller = (
                tool_execution_controller
                or ToolExecutionController(
                    limits=tool_execution_limits,
                    ledger=tool_idempotency_ledger,
                    clock=self._clock_source.now_monotonic,
                    timer_scheduler=self._timer_scheduler,
                    metrics_sink=metrics_sink,
                    trace_sink=trace_sink,
                )
            )
            self.planner = self._build_planner(
                tool_executor=tool_executor,
                policy=policy,
                approval_handler=approval_handler,
                controller=self.tool_execution_controller,
            )
        self._unregister_runtime_owner = register_runtime_owner(self.store, self)

    def _build_planner(
        self,
        *,
        tool_executor: Optional[ToolExecutor],
        policy: Optional[Any],
        approval_handler: ApprovalHandler | None,
        controller: ToolExecutionController,
    ) -> ToolPlanner:
        """Construct the default planner. Called only when no explicit
        planner was passed to ``__init__``."""
        # Lazy import to avoid a top-level circular dependency; execute_tool
        # lives in the global tool registry.
        from kaji.runtime.tools.registry import execute_tool  # noqa: PLC0415

        async def default_executor(invocation: ToolInvocation) -> Any:
            return await execute_tool(invocation)

        executor: ToolExecutor = (
            tool_executor if tool_executor is not None else default_executor
        )
        specs = {spec.name: spec for spec in self.tools}
        return ToolPlanner(
            executor=executor,
            policy=policy,
            approval_handler=approval_handler,
            specs=specs,
            controller=controller,
            id_factory=self._id_factory,
            clock=self._clock_source,
        )

    async def drain_tools(self, timeout: float) -> list[str]:
        """Report tool calls still running after a bounded shutdown drain."""
        return await self.tool_execution_controller.drain_tools(timeout)

    async def drain_providers(self, timeout: float) -> list[str]:
        """Release quarantined session leases after real provider settlement."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a finite non-negative number")
        if not math.isfinite(float(timeout)) or timeout < 0:
            raise ValueError("timeout must be a finite non-negative number")
        records = list(self._provider_quarantine.values())
        if records:

            async def wait_for_records() -> None:
                await asyncio.gather(
                    *(asyncio.shield(record.settlement) for record in records),
                    return_exceptions=True,
                )

            settled = asyncio.create_task(wait_for_records())
            expired = asyncio.get_running_loop().create_future()
            timer = self._timer_scheduler.call_later(
                float(timeout),
                lambda: expired.set_result(None) if not expired.done() else None,
            )
            try:
                await asyncio.wait(
                    {settled, expired}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                timer.cancel()
                if not expired.done():
                    expired.cancel()
            if not settled.done():
                settled.cancel()
                with suppress(asyncio.CancelledError):
                    await settled
        for record in records:
            if not record.settlement.done() or record.settlement.cancelled():
                continue
            if record.settlement.exception() is not None:
                continue
            if self._provider_quarantine.get(record.session_id) is not record:
                continue
            await record.lease.release()
            await self.coordinator.clear_quarantine(record.session_id)
            self._provider_quarantine.pop(record.session_id, None)
            record.release_lifecycle()
        return sorted(self._provider_quarantine)

    async def purge_session(self, session_id: str) -> bool:
        """Delete one settled generation and converge every shared owner."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise TypeError("session_id must be a non-empty string")
        if not supports_coordinated_session_purge(self.store):
            raise SessionPurgeUnsupportedError(session_id, "event_store")

        with store_session_purge(
            cast(EventStore, self.store),
            session_id,
            coordinated=True,
            retry_cleanup=True,
        ) as lease:
            owners = lease.cleanup_targets
            for owner in owners:
                unsupported = owner.session_purge_unsupported_component()
                if unsupported is not None:
                    raise SessionPurgeUnsupportedError(session_id, unsupported)
            if any(owner.is_session_busy(session_id) for owner in owners):
                raise SessionPurgeBusyError(session_id)

            if not lease.recovering:
                closures = await asyncio.gather(
                    *(
                        owner.close_session_subscriptions(
                            session_id,
                            lease.authorization,
                        )
                        for owner in owners
                    ),
                    return_exceptions=True,
                )
                closure_failure = next(
                    (
                        result
                        for result in closures
                        if isinstance(result, BaseException)
                    ),
                    None,
                )
                if closure_failure is not None:
                    raise closure_failure

            commit = asyncio.create_task(
                self._finish_irreversible_purge(session_id, lease)
            )
            cancelled = False
            while not commit.done():
                try:
                    await asyncio.shield(commit)
                except asyncio.CancelledError:
                    cancelled = True
            result = commit.result()
            if cancelled:
                raise asyncio.CancelledError
            return result

    async def _finish_irreversible_purge(
        self,
        session_id: str,
        lease: StoreSessionPurgeLease,
    ) -> bool:
        if lease.recovering:
            purged = lease.physical_existed
        else:
            assert supports_coordinated_session_purge(self.store)
            purged = await self.store._purge_session_authorized(
                session_id,
                lease.authorization,
            )

        failures: list[BaseException] = []
        for owner in lease.cleanup_targets:
            try:
                owner.clear_session_caches(session_id)
            except BaseException as error:
                failures.append(error)
        settlements = await asyncio.gather(
            *(
                owner.release_settled_session(session_id)
                for owner in lease.cleanup_targets
            ),
            return_exceptions=True,
        )
        failures.extend(
            result for result in settlements if isinstance(result, BaseException)
        )
        if failures:
            raise failures[0]
        finish_session_cleanup(lease)
        return purged

    def session_purge_unsupported_component(
        self,
    ) -> SessionPurgeComponent | None:
        if not callable(getattr(self.journal, "close_session_subscriptions", None)):
            return "event_delivery"
        if not callable(
            getattr(self.tool_execution_controller.ledger, "release_settled", None)
        ):
            return "tool_idempotency_ledger"
        return None

    def is_session_busy(self, session_id: str) -> bool:
        return self._has_busy_session_state(session_id)

    async def close_session_subscriptions(
        self,
        session_id: str,
        authorization: SessionPurgeAuthorization,
    ) -> None:
        close = getattr(self.journal, "close_session_subscriptions", None)
        if not callable(close):
            raise SessionPurgeUnsupportedError(session_id, "event_delivery")
        await close(session_id, authorization)

    def clear_session_caches(self, session_id: str) -> None:
        self._projectors.pop(session_id, None)
        self._projection_locks.pop(session_id, None)
        self._active_projection_sessions.pop(session_id, None)
        for turn_id, collector in tuple(self._turn_event_collectors.items()):
            if collector.session_id == session_id:
                self._turn_event_collectors.pop(turn_id, None)
        self._context_diagnostics.pop(session_id, None)
        self._stream_diagnostics.pop(session_id, None)
        self._provider_quarantine.pop(session_id, None)

    async def release_settled_session(self, session_id: str) -> None:
        release = getattr(
            self.tool_execution_controller.ledger, "release_settled", None
        )
        if not callable(release):
            raise SessionPurgeUnsupportedError(
                session_id,
                "tool_idempotency_ledger",
            )
        await release(session_id)

    def _has_busy_session_state(self, session_id: str) -> bool:
        lock = self._projection_locks.get(session_id)
        return (
            session_id in self._active_projection_sessions
            or (lock is not None and lock.locked())
            or any(
                collector.session_id == session_id
                for collector in self._turn_event_collectors.values()
            )
            or session_id in self._provider_quarantine
            or self.tool_execution_controller.has_active_session(session_id)
        )

    def close(self) -> None:
        """Reject future turns without claiming active providers were killed."""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Agent runtime is closed")

    def effective_limits(self) -> EffectiveRuntimeLimits:
        """Return an immutable snapshot of the limits this runtime will use."""
        tool_limits = self.tool_execution_controller.limits
        return EffectiveRuntimeLimits(
            max_tool_iterations=self.strategy.max_iterations,
            context_window_turns=self.context_window.max_turns,
            context_window_characters=self.context_window.max_characters,
            tool_max_parallel=tool_limits.max_parallel,
            tool_timeout_seconds=tool_limits.timeout_seconds,
            approval_timeout_seconds=tool_limits.approval_timeout_seconds,
            turn_timeout_seconds=self.turn_limits.timeout_seconds,
            provider_cancellation_grace_seconds=(
                self.turn_limits.provider_cancellation_grace_seconds
            ),
            provider_text_max_bytes=self.turn_limits.provider_text_max_bytes,
            provider_tool_arguments_max_bytes=(
                self.turn_limits.provider_tool_arguments_max_bytes
            ),
            provider_response_max_bytes=self.turn_limits.provider_response_max_bytes,
            provider_tool_calls_max=self.turn_limits.provider_tool_calls_max,
        )

    def _resolve_turn_context(self, context: TurnContext | None) -> TurnContext:
        default = self._default_context
        if context is None:
            return (
                default.refresh_generated_ids(self._id_factory)
                if default is not None
                else TurnContext(id_factory=self._id_factory)
            )
        resolved_context = context.refresh_generated_ids(self._id_factory)
        if default is None:
            return resolved_context
        metadata = dict(default.metadata)
        metadata.update(resolved_context.metadata)
        deadlines = [
            value
            for value in (
                resolved_context.deadline_monotonic,
                default.deadline_monotonic,
            )
            if value is not None
        ]
        return TurnContext(
            principal_id=resolved_context.principal_id or default.principal_id,
            request_id=resolved_context.request_id,
            trace_id=resolved_context.trace_id,
            deadline_monotonic=min(deadlines) if deadlines else None,
            db=resolved_context.db if resolved_context.db is not None else default.db,
            metadata=metadata,
            id_factory=self._id_factory,
        )

    def _resolve_effective_deadline(self, context: TurnContext) -> TurnContext:
        now = self._clock_source.now_monotonic()
        deadline = now + self.turn_limits.timeout_seconds
        if context.deadline_monotonic is not None:
            deadline = min(deadline, context.deadline_monotonic)
        return context.with_deadline_monotonic(deadline)

    async def append_event(self, event: NewKajiEvent) -> StoredKajiEvent:
        """Commit an event and immediately advance its cached projection."""
        async with self._projection_scope(event.session_id):
            return await self._append_event_scoped(event)

    async def _append_event_scoped(self, event: NewKajiEvent) -> StoredKajiEvent:
        projector = self._projector_for(event.session_id)
        async with self._projection_lock(event.session_id):
            if not projector.initialized:
                await projector.sync(self.store)
            stored = await self.journal.commit(event)
            if stored.sequence == projector.cursor + 1:
                projector.apply(stored)
            elif stored.sequence > projector.cursor:
                # Another canonical writer committed between this runtime's
                # suffix read and commit. Pull the detected gap plus this event.
                await projector.sync(self.store)
            collector = (
                self._turn_event_collectors.get(stored.turn_id)
                if stored.turn_id is not None
                else None
            )
            if collector is not None:
                assert stored.sequence is not None
                if stored.sequence == collector.cursor + 1:
                    collector.events.append(_copy_stored_event(stored))
                    collector.cursor = stored.sequence
                else:
                    await self._collect_turn_events_through(
                        collector,
                        stored.sequence,
                    )
            return _copy_stored_event(stored)

    async def _observe_stored_event(self, event: StoredKajiEvent) -> None:
        """Advance projection and active turn collection for an external append."""
        stored = require_stored_event(event)
        assert stored.sequence is not None
        async with self._projection_scope(stored.session_id):
            async with self._projection_lock(stored.session_id):
                persisted = [
                    revalidate_stored_event(item)
                    for item in await self.store.get_events(
                        stored.session_id,
                        after_sequence=stored.sequence - 1,
                        limit=1,
                    )
                ]
                if len(persisted) != 1 or persisted[0].model_dump(
                    mode="json"
                ) != stored.model_dump(mode="json"):
                    raise ValueError("observed event is not in the runtime journal")
                projector = self._projector_for(stored.session_id)
                if not projector.initialized or stored.sequence > projector.cursor:
                    await projector.sync(self.store)
                collector = (
                    self._turn_event_collectors.get(stored.turn_id)
                    if stored.turn_id is not None
                    else None
                )
                if collector is not None:
                    await self._collect_turn_events_through(
                        collector,
                        stored.sequence,
                    )

    async def _collect_turn_events_through(
        self,
        collector: _TurnEventCollector,
        sequence: int,
    ) -> None:
        """Collect a persisted suffix once, including externally appended gaps."""
        if sequence <= collector.cursor:
            return
        suffix = [
            revalidate_stored_event(event)
            for event in await self.store.get_events(
                collector.session_id,
                after_sequence=collector.cursor,
                limit=sequence - collector.cursor,
            )
        ]
        for event in suffix:
            assert event.sequence is not None
            if event.sequence > sequence:
                break
            if event.turn_id == collector.turn_id:
                collector.events.append(_copy_stored_event(event))
            collector.cursor = event.sequence
        if collector.cursor < sequence:
            raise RuntimeError("turn event collector could not close a sequence gap")

    def _projector_for(self, session_id: str) -> SessionProjector:
        projector = self._projectors.get(session_id)
        if projector is None:
            projector = SessionProjector(
                session_id,
                metrics_sink=self._metrics,
                context_window=self.context_window,
            )
            self._projectors[session_id] = projector
            self._trim_projection_cache()
        else:
            self._projectors.move_to_end(session_id)
        return projector

    @asynccontextmanager
    async def _projection_scope(self, session_id: str) -> AsyncIterator[None]:
        with store_session_operation(self.store, session_id):
            self._active_projection_sessions[session_id] = (
                self._active_projection_sessions.get(session_id, 0) + 1
            )
            try:
                yield
            finally:
                remaining = self._active_projection_sessions[session_id] - 1
                if remaining == 0:
                    self._active_projection_sessions.pop(session_id, None)
                else:
                    self._active_projection_sessions[session_id] = remaining
                self._trim_projection_cache()

    @asynccontextmanager
    async def _turn_scope(
        self,
        session_id: str,
        token: CancellationToken,
        deadline_monotonic: float,
    ) -> AsyncIterator[None]:
        with store_session_operation(self.store, session_id):
            async with self._turn_scope_unfenced(
                session_id,
                token,
                deadline_monotonic,
            ):
                yield

    @asynccontextmanager
    async def _turn_scope_unfenced(
        self,
        session_id: str,
        token: CancellationToken,
        deadline_monotonic: float,
    ) -> AsyncIterator[None]:
        """Measure coordinator wait without coupling sinks to shared coordinators."""
        started = self._clock_source.now_monotonic()
        recorded = False
        try:
            async with self.coordinator.acquire(
                session_id,
                token,
                deadline_monotonic=deadline_monotonic,
                clock=self._clock_source,
                scheduler=self._timer_scheduler,
            ) as lease:
                record_metric(
                    self._metrics,
                    "kaji.turn.queue_wait_ms",
                    (self._clock_source.now_monotonic() - started) * 1_000,
                )
                recorded = True
                try:
                    yield
                except ProviderCancellationContractViolation as error:
                    settlement = error._settlement
                    if not isinstance(settlement, asyncio.Task):
                        raise RuntimeError(
                            "provider violation is missing tracked settlement"
                        ) from error
                    transferred = lease.transfer()
                    settlement.add_done_callback(
                        lambda task: task.exception() if not task.cancelled() else None
                    )
                    release_lifecycle = retain_store_session_quarantine(
                        self.store,
                        session_id,
                    )
                    record = _ProviderQuarantine(
                        session_id=session_id,
                        lease=transferred,
                        settlement=settlement,
                        release_lifecycle=release_lifecycle,
                    )
                    self._provider_quarantine[session_id] = record
                    try:
                        await self.coordinator.quarantine(session_id)
                    except BaseException:
                        # Ownership already transferred to the quarantine record.
                        # Keep it drainable even when coordinator setup fails.
                        raise
                    raise
        finally:
            if not recorded:
                record_metric(
                    self._metrics,
                    "kaji.turn.queue_wait_ms",
                    (self._clock_source.now_monotonic() - started) * 1_000,
                )

    def _trim_projection_cache(self) -> None:
        while len(self._projectors) > self._projection_cache_capacity:
            candidate = None
            for session_id in self._projectors:
                lock = self._projection_locks.get(session_id)
                if session_id not in self._active_projection_sessions and (
                    lock is None or not lock.locked()
                ):
                    candidate = session_id
                    break
            if candidate is None:
                return
            self._projectors.pop(candidate, None)
            self._projection_locks.pop(candidate, None)
            self._context_diagnostics.pop(candidate, None)
            self._stream_diagnostics.pop(candidate, None)

    @property
    def projection_cache_size(self) -> int:
        return len(self._projectors)

    def _projection_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._projection_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._projection_locks[session_id] = lock
        return lock

    async def _sync_projection(self, session_id: str) -> SessionProjector:
        projector = self._projector_for(session_id)
        async with self._projection_lock(session_id):
            await projector.sync(self.store)
        return projector

    def context_diagnostics(self, session_id: str) -> ContextDiagnostics | None:
        """Return diagnostics from the latest provider context for a session."""
        return self._context_diagnostics.get(session_id)

    def stream_diagnostics(self, session_id: str) -> StreamDiagnostics | None:
        """Return immutable counters from the latest provider call for a session."""
        return self._stream_diagnostics.get(session_id)

    def context_index_stats(self, session_id: str) -> ContextIndexStats | None:
        """Return index counters without creating a session projector."""
        projector = self._projectors.get(session_id)
        return None if projector is None else projector.context_index_stats

    async def _emit(self, event: NewKajiEvent) -> StoredKajiEvent:
        return await self.append_event(event)

    async def _emit_for_turn(
        self, event: NewKajiEvent, turn_id: str
    ) -> StoredKajiEvent:
        """Attach the active turn identity without mutating event drafts."""
        if event.turn_id != turn_id:
            event = event.model_copy(update={"turn_id": turn_id})
        return await self._emit(event)

    async def turn(
        self,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        cancellation_token: Optional[CancellationToken] = None,
        context: TurnContext | None = None,
    ) -> TurnResult:
        """Run one full agent turn and return a structured result.

        One call wraps the ceremony of bootstrapping a session, sending the
        prompt, running the ReAct loop, and slicing the new events out of the
        store. Errors from the underlying loop propagate unchanged.

        Args:
            prompt: The user message to send.
            session_id: Existing session to reuse; a fresh UUID hex is
                generated when omitted.
            cancellation_token: Optional token threaded into ``send``.

        Returns:
            ``TurnResult`` with ``text``, ``session_id``, ``tool_call_events``,
            and the full ``events`` slice emitted by this call.
        """
        with event_defaults(self._id_factory, self._clock_source):
            self._ensure_open()
            sid = session_id or self._id_factory.next("session")
            token = cancellation_token or CancellationToken()
            resolved_context = self._resolve_effective_deadline(
                self._resolve_turn_context(context)
            )
            assert resolved_context.deadline_monotonic is not None
            turn_id = self._id_factory.next("turn")
            acquired = False
            try:
                async with self._turn_scope(
                    sid, token, resolved_context.deadline_monotonic
                ):
                    acquired = True
                    async with self._projection_scope(sid):
                        projector = await self._sync_projection(sid)
                        collector = _TurnEventCollector(
                            session_id=sid,
                            turn_id=turn_id,
                            cursor=projector.cursor,
                        )
                        self._turn_event_collectors[turn_id] = collector
                        try:
                            return await self._turn_unlocked(
                                sid,
                                prompt,
                                token,
                                turn_id,
                                projector,
                                collector.events,
                                resolved_context,
                            )
                        finally:
                            self._turn_event_collectors.pop(turn_id, None)
            except TurnTimeoutError as error:
                if error.phase == "queue":
                    await self._record_turn_failure(sid, turn_id, error)
                raise
            except asyncio.CancelledError:
                if token.is_cancelled and not acquired:
                    await self._emit_for_turn(
                        CancellationCompleted(session_id=sid, turn_id=turn_id),
                        turn_id,
                    )
                raise
            except ProviderCancellationContractViolation as error:
                if not acquired:
                    await self._record_turn_failure(sid, turn_id, error)
                raise

    async def _turn_unlocked(
        self,
        session_id: str,
        prompt: str,
        cancellation_token: CancellationToken,
        turn_id: str,
        projector: SessionProjector,
        turn_events: list[StoredKajiEvent],
        context: TurnContext,
    ) -> TurnResult:
        """Run ``turn`` while the caller holds the session coordinator."""
        cancellation_token.raise_if_cancelled()
        if projector.cursor == 0:
            await self._emit_for_turn(
                SessionCreated(session_id=session_id),
                turn_id,
            )
        await self._send_unlocked(
            session_id,
            prompt,
            cancellation_token,
            turn_id,
            context,
        )
        result_events = [_copy_stored_event(event) for event in turn_events]
        text = "".join(
            getattr(e, "content", "")
            for e in result_events
            if e.type == EventType.AGENT_MESSAGE_COMPLETED
        )
        tool_call_events: List[StoredKajiEvent] = [
            _copy_stored_event(e)
            for e in result_events
            if e.type == EventType.TOOL_CALL_REQUESTED
        ]
        return TurnResult(
            text=text,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_events=tool_call_events,
            events=result_events,
        )

    async def send(
        self,
        session_id: str,
        content: str,
        cancellation_token: Optional[CancellationToken] = None,
        *,
        context: TurnContext | None = None,
    ) -> None:
        """Append a user message and immediately run the agent turn.

        This is the idiomatic one-shot call:

            await runtime.send("s1", "What time is it?")

        For more control (batch-append, replay, pre-seeding), call
        ``append_event(UserMessage(...))`` and ``run_turn()`` separately.
        """
        with event_defaults(self._id_factory, self._clock_source):
            self._ensure_open()
            token = cancellation_token or CancellationToken()
            resolved_context = self._resolve_effective_deadline(
                self._resolve_turn_context(context)
            )
            assert resolved_context.deadline_monotonic is not None
            turn_id = self._id_factory.next("turn")
            acquired = False
            try:
                async with self._turn_scope(
                    session_id, token, resolved_context.deadline_monotonic
                ):
                    acquired = True
                    async with self._projection_scope(session_id):
                        await self._sync_projection(session_id)
                        await self._send_unlocked(
                            session_id,
                            content,
                            token,
                            turn_id,
                            resolved_context,
                        )
            except TurnTimeoutError as error:
                if error.phase == "queue":
                    await self._record_turn_failure(session_id, turn_id, error)
                raise
            except asyncio.CancelledError:
                if token.is_cancelled and not acquired:
                    await self._emit_for_turn(
                        CancellationCompleted(session_id=session_id, turn_id=turn_id),
                        turn_id,
                    )
                raise
            except ProviderCancellationContractViolation as error:
                if not acquired:
                    await self._record_turn_failure(session_id, turn_id, error)
                raise

    async def _send_unlocked(
        self,
        session_id: str,
        content: str,
        cancellation_token: CancellationToken,
        turn_id: str,
        context: TurnContext,
    ) -> None:
        """Append a user message and run while the session lease is held."""
        cancellation_token.raise_if_cancelled()
        await self._emit_for_turn(
            UserMessage(session_id=session_id, content=content),
            turn_id,
        )
        await self._run_turn_unlocked(
            session_id,
            cancellation_token,
            turn_id,
            context,
        )

    async def history(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1_024,
    ) -> List[StoredKajiEvent]:
        """Return a bounded cursor page of persisted events in append order."""
        return [
            revalidate_stored_event(event)
            for event in await self.store.get_events(
                session_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        ]

    async def run_turn(
        self,
        session_id: str,
        cancellation_token: Optional[CancellationToken] = None,
        *,
        context: TurnContext | None = None,
    ) -> None:
        """Run the core ReAct-style agent loop for a given session.

        The event log must already contain at least one ``UserMessage`` for
        ``session_id``. To send a message and run in one call, use ``send()``.
        """
        with event_defaults(self._id_factory, self._clock_source):
            self._ensure_open()
            token = cancellation_token or CancellationToken()
            resolved_context = self._resolve_effective_deadline(
                self._resolve_turn_context(context)
            )
            assert resolved_context.deadline_monotonic is not None
            turn_id = self._id_factory.next("turn")
            acquired = False
            try:
                async with self._turn_scope(
                    session_id, token, resolved_context.deadline_monotonic
                ):
                    acquired = True
                    async with self._projection_scope(session_id):
                        await self._sync_projection(session_id)
                        await self._run_turn_unlocked(
                            session_id,
                            token,
                            turn_id,
                            resolved_context,
                        )
            except TurnTimeoutError as error:
                if error.phase == "queue":
                    await self._record_turn_failure(session_id, turn_id, error)
                raise
            except asyncio.CancelledError:
                if token.is_cancelled and not acquired:
                    await self._emit_for_turn(
                        CancellationCompleted(session_id=session_id, turn_id=turn_id),
                        turn_id,
                    )
                raise
            except ProviderCancellationContractViolation as error:
                if not acquired:
                    await self._record_turn_failure(session_id, turn_id, error)
                raise

    async def _record_turn_failure(
        self, session_id: str, turn_id: str, error: Exception
    ) -> None:
        fields: dict[str, Any] = {}
        public_error = _PUBLIC_TURN_FAILURE
        if isinstance(error, TurnTimeoutError):
            public_error = _PUBLIC_TURN_TIMEOUT
            fields = {
                "error_code": error.code,
                "phase": error.phase,
                "retryable": error.retryable,
                "outcome": error.outcome,
            }
        elif isinstance(error, ProviderCancellationContractViolation):
            fields = {
                "error_code": error.code,
                "phase": error.phase,
                "retryable": error.retryable,
                "outcome": error.outcome,
            }
        elif isinstance(error, ProviderOutputLimitError):
            public_error = str(error)
            fields = {
                "error_code": error.code,
                "phase": error.phase,
                "retryable": error.retryable,
                "outcome": error.outcome,
            }
        try:
            await self._emit_for_turn(
                AgentTurnFailed(
                    session_id=session_id,
                    turn_id=turn_id,
                    error=public_error,
                    **fields,
                ),
                turn_id,
            )
        except Exception as log_error:
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Failed to record terminal agent turn failure",
                log_error,
            )

    async def _run_turn_unlocked(
        self,
        session_id: str,
        token: CancellationToken,
        turn_id: str,
        context: TurnContext,
    ) -> None:
        """Run the turn body and record any ordinary terminal failure."""
        started = self._clock_source.now_monotonic()
        iterations = 0
        outcome = "completed"
        trace_attributes: dict[TraceAttributeName, str] = {
            "session.id": session_id,
            "turn.id": turn_id,
            "request.id": context.request_id,
            "trace.id": context.trace_id,
        }
        span = start_span(self._trace, "kaji.turn", trace_attributes)
        try:
            iterations = await self._run_turn_body(
                session_id,
                token,
                turn_id,
                context,
            )
            if token.is_cancelled:
                outcome = "cancelled"
        except asyncio.CancelledError as error:
            outcome = "cancelled"
            span_record_error(span, error)
            raise
        except Exception as error:
            outcome = "failed"
            span_record_error(span, error)
            await self._record_turn_failure(session_id, turn_id, error)
            raise
        finally:
            record_metric(
                self._metrics,
                "kaji.turn.duration_ms",
                (self._clock_source.now_monotonic() - started) * 1_000,
                outcome=outcome,
            )
            record_metric(
                self._metrics,
                "kaji.turn.iterations",
                iterations,
                outcome=outcome,
            )
            span_end(span)

    async def _run_turn_body(
        self,
        session_id: str,
        token: CancellationToken,
        turn_id: str,
        turn_context: TurnContext,
    ) -> int:
        """Run the ReAct loop while the caller holds the session lease."""
        token.raise_if_cancelled()
        if (
            self.strategy.allow_tool_calls
            and self.tools
            and turn_context.principal_id is None
        ):
            raise MissingToolIdentityError()

        emit_turn_event = _TurnEventEmitter(self, turn_id)
        provider_tools = self._tool_payload if self.strategy.allow_tool_calls else []

        iterations = 0
        for iteration in range(self.strategy.max_iterations):
            iterations = iteration + 1
            if token.is_cancelled:
                await emit_turn_event(CancellationCompleted(session_id=session_id))
                return iterations

            # Persist an explicit provider-output/tool-batch boundary so cold
            # replay can distinguish consecutive tool-only iterations.
            await emit_turn_event(AgentReasoningStarted(session_id=session_id))

            # 1. Reuse the projection advanced by each committed event.
            projector = self._projector_for(session_id)

            # 1a. RAG: retrieve chunks relevant to the latest user message and
            # prepend them to the system prompt so the model has grounded context.
            rag_system_prefix = ""
            if self._rag is not None:
                last_user = projector.latest_user_content()
                if last_user:
                    try:
                        chunks = await self._rag.retrieve(
                            last_user, top_k=self._rag_top_k
                        )
                        if chunks:
                            joined = "\n\n".join(c.text for c in chunks)
                            rag_system_prefix = f"## Relevant context\n\n{joined}\n\n"
                    except Exception as error:  # retrieval must never crash the turn
                        log_redacted_failure(
                            logger,
                            logging.WARNING,
                            "RAG retrieval failed",
                            error,
                        )

            prompt_for_turn = (
                SystemPrompt(rag_system_prefix + self.prompt.template)
                if rag_system_prefix
                else self.prompt
            )
            context = projector.build_projected_context(
                prompt_for_turn,
                window=self.context_window,
            )
            self._context_diagnostics[session_id] = context.diagnostics
            messages = context.messages

            # 2. Surface tools to the provider (cached payload, see __init__).
            response = RuntimeStreamAccumulator(self._provider_response_limits)
            stream_metrics: TokenMetrics | None = None
            stream_cost_usd: float | None = None

            # 3. Stream from Provider. The provider raises asyncio.CancelledError
            # when the token flips mid-stream; we catch it here so the canonical
            # CancellationCompleted event still reaches observers. Re-raise if
            # the cancel came from outside our token (e.g. parent task cancel)
            # so structured concurrency stays intact.
            family = provider_family(self.provider)
            provider_started = self._clock_source.now_monotonic()
            provider_diagnostics = ProviderDiagnosticsSink()
            provider_status = "success"
            provider_span = start_span(
                self._trace,
                "kaji.provider",
                {
                    "session.id": session_id,
                    "turn.id": turn_id,
                    "request.id": turn_context.request_id,
                    "trace.id": turn_context.trace_id,
                    "provider.family": family,
                },
            )
            try:
                assert turn_context.deadline_monotonic is not None
                async with ProviderDeadlineScope(
                    parent=token,
                    deadline_monotonic=turn_context.deadline_monotonic,
                    cancellation_grace_seconds=(
                        self.turn_limits.provider_cancellation_grace_seconds
                    ),
                    clock=self._clock_source,
                    scheduler=self._timer_scheduler,
                ) as provider_scope:
                    try:
                        with provider_diagnostics_scope(provider_diagnostics):
                            async for chunk in provider_scope.consume(
                                self.provider.generate_stream(
                                    messages,
                                    provider_tools,
                                    cancellation_token=provider_scope.token,
                                    response_limits=self._provider_response_limits,
                                )
                            ):
                                deltas = response.accept(chunk)
                                if chunk.metrics is not None:
                                    stream_metrics = chunk.metrics.model_copy(deep=True)
                                if chunk.cost_usd is not None:
                                    stream_cost_usd = chunk.cost_usd
                                for delta in deltas:
                                    await emit_turn_event(
                                        AgentMessageDelta(
                                            session_id=session_id, delta=delta
                                        )
                                    )
                    finally:
                        residual = response.flush()
                        if residual is not None:
                            await emit_turn_event(
                                AgentMessageDelta(session_id=session_id, delta=residual)
                            )
            except asyncio.CancelledError as error:
                provider_status = "cancelled"
                span_record_error(provider_span, error)
                current = asyncio.current_task()
                parent_cancelling = current is not None and current.cancelling() > 0
                provider_cancelled = provider_scope.token.is_cancelled
                if parent_cancelling or (
                    not token.is_cancelled and not provider_cancelled
                ):
                    # Cancellation came from outside our token (parent task).
                    # Re-raise so the caller observes structured cancellation.
                    raise
                # Shield the terminal emit: if a parent task is also being
                # cancelled, we still want CancellationCompleted to reach
                # observers before unwinding.
                await asyncio.shield(
                    emit_turn_event(CancellationCompleted(session_id=session_id))
                )
                return iterations
            except Exception as error:
                provider_status = "error"
                span_record_error(provider_span, error)
                raise
            finally:
                response.set_provider_diagnostics(provider_diagnostics.diagnostics)
                self._stream_diagnostics[session_id] = response.diagnostics
                record_metric(
                    self._metrics,
                    "kaji.provider.duration_ms",
                    (self._clock_source.now_monotonic() - provider_started) * 1_000,
                    provider_family=family,
                    status=provider_status,
                )
                record_metric(
                    self._metrics,
                    "kaji.provider.retries",
                    0,
                    provider_family=family,
                )
                span_end(provider_span)

            # 4. Finalize text message
            full_response = response.content()
            self._stream_diagnostics[session_id] = response.diagnostics
            if full_response:
                tokens: EventTokenUsage | None = None
                if stream_metrics is not None:
                    tokens = EventTokenUsage(
                        input=stream_metrics.prompt_tokens,
                        output=stream_metrics.completion_tokens,
                    )
                await emit_turn_event(
                    AgentMessageCompleted(
                        session_id=session_id,
                        content=full_response,
                        tokens=tokens,
                        cost_usd=stream_cost_usd,
                    )
                )
            # 5. Break if done
            tool_calls = response.tool_calls
            if not tool_calls or not self.strategy.allow_tool_calls:
                break

            if turn_context.principal_id is None:
                # A provider must not bypass identity enforcement by returning
                # an unadvertised tool call.
                raise MissingToolIdentityError()

            # 6. Execute one bounded tool batch
            await self.planner.execute_batch(
                session_id,
                tool_calls,
                emit_turn_event,
                turn_id=turn_id,
                turn_context=turn_context,
                cancellation_token=token,
                approval_journal=self.journal,
            )

            # The planner has emitted ToolCallCompleted/Failed events.
            # The loop continues, which re-evaluates state including the new tool results.
            if iteration == self.strategy.max_iterations - 1:
                await emit_turn_event(
                    AgentTurnExhausted(
                        session_id=session_id,
                        max_iterations=self.strategy.max_iterations,
                        pending_tool_calls=tool_calls,
                        reason="max_iterations",
                    )
                )
        return iterations
