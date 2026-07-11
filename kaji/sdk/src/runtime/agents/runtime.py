import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.coordinator import (
    TurnCoordinator,
    default_coordinator_for_store,
)
from kaji.runtime.agents.context import (
    ContextDiagnostics,
    ContextWindow,
    build_context,
)
from kaji.runtime.agents.planner import ApprovalHandler, ToolPlanner
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.tools.registry import ToolSpec
from kaji.infra.events.journal import InMemoryEventJournal, SplitEventJournal
from kaji.infra.events.protocols import EventBusProtocol, EventJournal
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
    require_stored_event,
)
from kaji.infra.events.store import EventStore
from kaji.infra.events.types import EventType
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.types import TokenMetrics
from kaji.runtime.sessions.projector import SessionProjector


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


logger = logging.getLogger(__name__)

_PUBLIC_TURN_FAILURE = "Agent turn failed"

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]


def _copy_stored_event(event: StoredKajiEvent) -> StoredKajiEvent:
    return require_stored_event(event.model_copy(deep=True))


class AgentRuntime:
    """A generic, provider-agnostic agent runtime.

    Consumes Kaji events, maintains session state, calls an abstract ModelProvider,
    executes scatter-gather tool workflows via ToolPlanner.

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
        bus: Optional[EventBusProtocol],
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
        approval_handler: Optional[ApprovalHandler] = None,
        user_id: str = "agent",
        journal: Optional[EventJournal] = None,
        coordinator: Optional[TurnCoordinator] = None,
        context_window: ContextWindow | None = None,
    ):
        resolved_journal: EventJournal = journal or (
            SplitEventJournal(store, bus)
            if bus is not None
            else InMemoryEventJournal(store)
        )
        if resolved_journal.store is not store:
            raise ValueError("store must be the same object as journal.store")
        self.bus = bus
        self.store = store
        self.journal = resolved_journal
        self.coordinator = (
            coordinator
            if coordinator is not None
            else default_coordinator_for_store(store)
        )
        self.provider = provider
        self._user_id = user_id
        self.prompt = SystemPrompt(system_prompt)
        self.strategy = strategy or AgentStrategy()
        self.context_window = context_window or ContextWindow()
        store_capacity = getattr(store, "max_sessions", 1_000)
        self._projection_cache_capacity = (
            store_capacity
            if isinstance(store_capacity, int) and store_capacity > 0
            else 1_000
        )
        self._projectors: OrderedDict[str, SessionProjector] = OrderedDict()
        self._projection_locks: dict[str, asyncio.Lock] = {}
        self._active_projection_sessions: dict[str, int] = {}
        self._turn_event_collectors: dict[str, list[StoredKajiEvent]] = {}
        self._context_diagnostics: dict[str, ContextDiagnostics] = {}
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
        self.planner: ToolPlanner = (
            planner
            if planner is not None
            else self._build_planner(
                tool_executor=tool_executor,
                policy=policy,
                approval_handler=approval_handler,
            )
        )

    def _build_planner(
        self,
        *,
        tool_executor: Optional[ToolExecutor],
        policy: Optional[Any],
        approval_handler: Optional[ApprovalHandler],
    ) -> ToolPlanner:
        """Construct the default planner. Called only when no explicit
        planner was passed to ``__init__``."""
        # Lazy import to avoid a top-level circular dependency; execute_tool
        # lives in the global tool registry.
        from kaji.runtime.tools.registry import execute_tool  # noqa: PLC0415

        executor: ToolExecutor = tool_executor or (
            lambda name, args: execute_tool(self._user_id, name, args)
        )
        specs = {spec.name: spec for spec in self.tools}
        return ToolPlanner(
            executor=executor,
            policy=policy,
            approval_handler=approval_handler,
            specs=specs,
        )

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
                collector.append(_copy_stored_event(stored))
            return _copy_stored_event(stored)

    def _projector_for(self, session_id: str) -> SessionProjector:
        projector = self._projectors.get(session_id)
        if projector is None:
            projector = SessionProjector(session_id)
            self._projectors[session_id] = projector
            self._trim_projection_cache()
        else:
            self._projectors.move_to_end(session_id)
        return projector

    @asynccontextmanager
    async def _projection_scope(self, session_id: str) -> AsyncIterator[None]:
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
        sid = session_id or uuid.uuid4().hex
        token = cancellation_token or CancellationToken()
        async with self.coordinator.acquire(sid, token):
            async with self._projection_scope(sid):
                projector = await self._sync_projection(sid)
                turn_id = uuid.uuid4().hex
                turn_events: list[StoredKajiEvent] = []
                self._turn_event_collectors[turn_id] = turn_events
                try:
                    return await self._turn_unlocked(
                        sid,
                        prompt,
                        token,
                        turn_id,
                        projector,
                        turn_events,
                    )
                finally:
                    self._turn_event_collectors.pop(turn_id, None)

    async def _turn_unlocked(
        self,
        session_id: str,
        prompt: str,
        cancellation_token: CancellationToken,
        turn_id: str,
        projector: SessionProjector,
        turn_events: list[StoredKajiEvent],
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
    ) -> None:
        """Append a user message and immediately run the agent turn.

        This is the idiomatic one-shot call:

            await runtime.send("s1", "What time is it?")

        For more control (batch-append, replay, pre-seeding), call
        ``append_event(UserMessage(...))`` and ``run_turn()`` separately.
        """
        token = cancellation_token or CancellationToken()
        async with self.coordinator.acquire(session_id, token):
            async with self._projection_scope(session_id):
                await self._sync_projection(session_id)
                await self._send_unlocked(
                    session_id,
                    content,
                    token,
                    uuid.uuid4().hex,
                )

    async def _send_unlocked(
        self,
        session_id: str,
        content: str,
        cancellation_token: CancellationToken,
        turn_id: str,
    ) -> None:
        """Append a user message and run while the session lease is held."""
        cancellation_token.raise_if_cancelled()
        await self._emit_for_turn(
            UserMessage(session_id=session_id, content=content),
            turn_id,
        )
        await self._run_turn_unlocked(session_id, cancellation_token, turn_id)

    async def history(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1_024,
    ) -> List[StoredKajiEvent]:
        """Return a bounded cursor page of persisted events in append order."""
        return await self.store.get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def run_turn(
        self, session_id: str, cancellation_token: Optional[CancellationToken] = None
    ) -> None:
        """Run the core ReAct-style agent loop for a given session.

        The event log must already contain at least one ``UserMessage`` for
        ``session_id``. To send a message and run in one call, use ``send()``.
        """
        token = cancellation_token or CancellationToken()
        async with self.coordinator.acquire(session_id, token):
            async with self._projection_scope(session_id):
                await self._sync_projection(session_id)
                await self._run_turn_unlocked(session_id, token, uuid.uuid4().hex)

    async def _run_turn_unlocked(
        self,
        session_id: str,
        token: CancellationToken,
        turn_id: str,
    ) -> None:
        """Run the turn body and record any ordinary terminal failure."""
        try:
            await self._run_turn_body(session_id, token, turn_id)
        except Exception:
            try:
                await self._emit_for_turn(
                    AgentTurnFailed(
                        session_id=session_id,
                        turn_id=turn_id,
                        error=_PUBLIC_TURN_FAILURE,
                    ),
                    turn_id,
                )
            except Exception:
                # The original operation failure is the public API result. A
                # secondary journal failure must not replace it.
                logger.exception("Failed to record terminal agent turn failure")
            raise

    async def _run_turn_body(
        self,
        session_id: str,
        token: CancellationToken,
        turn_id: str,
    ) -> None:
        """Run the ReAct loop while the caller holds the session lease."""
        token.raise_if_cancelled()

        async def emit_turn_event(event: NewKajiEvent) -> None:
            await self._emit_for_turn(event, turn_id)

        for iteration in range(self.strategy.max_iterations):
            if token.is_cancelled:
                await emit_turn_event(CancellationCompleted(session_id=session_id))
                return

            # Persist an explicit provider-output/tool-batch boundary so cold
            # replay can distinguish consecutive tool-only iterations.
            await emit_turn_event(AgentReasoningStarted(session_id=session_id))

            # 1. Reuse the projection advanced by each committed event.
            state = self._projector_for(session_id).state

            # 1a. RAG: retrieve chunks relevant to the latest user message and
            # prepend them to the system prompt so the model has grounded context.
            rag_system_prefix = ""
            if self._rag is not None:
                last_user = next(
                    (
                        m["content"]
                        for m in reversed(state.messages)
                        if m["role"] == "user"
                    ),
                    None,
                )
                if last_user:
                    try:
                        chunks = await self._rag.retrieve(
                            last_user, top_k=self._rag_top_k
                        )
                        if chunks:
                            joined = "\n\n".join(c.text for c in chunks)
                            rag_system_prefix = f"## Relevant context\n\n{joined}\n\n"
                    except Exception as e:  # retrieval must never crash the turn
                        logger.warning("RAG retrieval failed: %s", e)

            prompt_for_turn = (
                SystemPrompt(rag_system_prefix + self.prompt.template)
                if rag_system_prefix
                else self.prompt
            )
            context = build_context(
                state,
                prompt_for_turn,
                window=self.context_window,
            )
            self._context_diagnostics[session_id] = context.diagnostics
            messages = context.messages

            # 2. Surface tools to the provider (cached payload, see __init__).
            full_response = ""
            tool_calls = []
            stream_metrics: TokenMetrics | None = None
            stream_cost_usd: float | None = None

            # 3. Stream from Provider. The provider raises asyncio.CancelledError
            # when the token flips mid-stream; we catch it here so the canonical
            # CancellationCompleted event still reaches observers. Re-raise if
            # the cancel came from outside our token (e.g. parent task cancel)
            # so structured concurrency stays intact.
            try:
                async for chunk in self.provider.generate_stream(
                    messages, self._tool_payload, cancellation_token=token
                ):
                    if chunk.delta:
                        full_response += chunk.delta
                        await emit_turn_event(
                            AgentMessageDelta(session_id=session_id, delta=chunk.delta)
                        )

                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
                    if chunk.metrics is not None:
                        stream_metrics = chunk.metrics
                    if chunk.cost_usd is not None:
                        stream_cost_usd = chunk.cost_usd
            except asyncio.CancelledError:
                current = asyncio.current_task()
                parent_cancelling = current is not None and current.cancelling() > 0
                if parent_cancelling or not token.is_cancelled:
                    # Cancellation came from outside our token (parent task).
                    # Re-raise so the caller observes structured cancellation.
                    raise
                # Shield the terminal emit: if a parent task is also being
                # cancelled, we still want CancellationCompleted to reach
                # observers before unwinding.
                await asyncio.shield(
                    emit_turn_event(CancellationCompleted(session_id=session_id))
                )
                return

            # 4. Finalize text message
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
            if not tool_calls or not self.strategy.allow_tool_calls:
                break

            # 6. Execute tools concurrently (Scatter-Gather)
            await self.planner.execute_scatter_gather(
                session_id, tool_calls, emit_turn_event
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
