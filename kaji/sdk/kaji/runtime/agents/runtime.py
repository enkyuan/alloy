import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import ContextBuilder
from kaji.runtime.agents.planner import ApprovalHandler, ToolPlanner
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.agents.state import SessionStateManager
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.tools.registry import ToolSpec
from kaji.infra.events.protocols import EventBusProtocol
from kaji.infra.events.schemas import (
    KajiEvent,
    AgentMessageCompleted,
    AgentMessageDelta,
    AgentReasoningStarted,
    CancellationCompleted,
    SessionCreated,
    UserMessage,
)
from kaji.infra.events.store import EventStore
from kaji.infra.events.types import EventType
from kaji.runtime.providers.base import ModelProvider


@dataclass(frozen=True)
class TurnResult:
    """The user-facing result of a single ``AgentRuntime.turn`` call.

    Attributes:
        text: All ``AgentMessageCompleted`` content emitted this turn, joined.
            May be empty when the provider returned only a tool call.
        tool_call_events: ``ToolCallRequested`` events emitted this turn.
            Named for the type honestly (not provider-neutral ``ToolCall``s).
        session_id: The session this turn ran against (auto-generated when
            no ``session_id`` was passed to ``turn``).
        events: Every event the runtime appended to the store this turn.
    """

    text: str
    session_id: str
    tool_call_events: List[KajiEvent] = field(default_factory=list)
    events: List[KajiEvent] = field(default_factory=list)

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]


class AgentRuntime:
    """A generic, provider-agnostic agent runtime.

    Consumes Kaji events, maintains session state, calls an abstract ModelProvider,
    executes scatter-gather tool workflows via ToolPlanner.

    ``planner`` is optional. When omitted, a default ``ToolPlanner`` is
    constructed from ``tool_executor`` (falls back to the global
    ``execute_tool`` registry), ``policy``, and ``approval_handler``, the same
    lazy-build pattern as the TypeScript ``AgentRuntime``. Pass an explicit
    ``planner`` (e.g. from ``AgentBuilder``) to use a scoped registry instead.
    """

    def __init__(
        self,
        bus: EventBusProtocol,
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
    ):
        self.bus = bus
        self.store = store
        self.provider = provider
        self._user_id = user_id
        self.prompt = SystemPrompt(system_prompt)
        self.strategy = strategy or AgentStrategy()
        self.state_manager = SessionStateManager(store)
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

    async def _emit(self, event: KajiEvent) -> None:
        """Commit an event to the source of truth and broadcast it."""
        await self.store.append(event)
        await self.bus.publish(event)

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
        existing = await self.store.get_events(sid)
        if not existing:
            await self._emit(SessionCreated(session_id=sid))
        snapshot_len = len(existing)
        await self.send(sid, prompt, cancellation_token=cancellation_token)
        all_events = await self.store.get_events(sid)
        turn_events = all_events[snapshot_len:]
        text = "".join(
            getattr(e, "content", "")
            for e in turn_events
            if e.type == EventType.AGENT_MESSAGE_COMPLETED
        )
        tool_call_events: List[KajiEvent] = [
            e for e in turn_events if e.type == EventType.TOOL_CALL_REQUESTED
        ]
        return TurnResult(
            text=text,
            session_id=sid,
            tool_call_events=tool_call_events,
            events=turn_events,
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

        For more control (batch-append, replay, pre-seeding) call
        ``store.append(UserMessage(...))`` and ``run_turn()`` separately.
        """
        await self._emit(UserMessage(session_id=session_id, content=content))
        await self.run_turn(session_id, cancellation_token)

    async def history(self, session_id: str) -> List[KajiEvent]:
        """Return the event log for ``session_id`` in append order.

        Shortcut for ``runtime.store.get_events(session_id)``.
        """
        return await self.store.get_events(session_id)

    async def run_turn(
        self, session_id: str, cancellation_token: Optional[CancellationToken] = None
    ) -> None:
        """Run the core ReAct-style agent loop for a given session.

        The event log must already contain at least one ``UserMessage`` for
        ``session_id``. To send a message and run in one call, use ``send()``.
        """
        token = cancellation_token or CancellationToken()

        await self._emit(AgentReasoningStarted(session_id=session_id))

        for _ in range(self.strategy.max_iterations):
            if token.is_cancelled:
                await self._emit(CancellationCompleted(session_id=session_id))
                return

            # 1. Materialize current session state from Event Log
            state = await self.state_manager.load_state(session_id)

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
            messages = ContextBuilder.build_messages(state, prompt_for_turn)

            # 2. Surface tools to the provider (cached payload, see __init__).
            full_response = ""
            tool_calls = []

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
                        await self._emit(
                            AgentMessageDelta(session_id=session_id, delta=chunk.delta)
                        )

                    if chunk.tool_calls:
                        tool_calls.extend(chunk.tool_calls)
            except asyncio.CancelledError:
                if not token.is_cancelled:
                    # Cancellation came from outside our token (parent task).
                    # Re-raise so the caller observes structured cancellation.
                    raise
                # Shield the terminal emit: if a parent task is also being
                # cancelled, we still want CancellationCompleted to reach
                # observers before unwinding.
                await asyncio.shield(
                    self._emit(CancellationCompleted(session_id=session_id))
                )
                return

            # 4. Finalize text message
            if full_response:
                await self._emit(
                    AgentMessageCompleted(session_id=session_id, content=full_response)
                )

            # 5. Break if done
            if not tool_calls or not self.strategy.allow_tool_calls:
                break

            # 6. Execute tools concurrently (Scatter-Gather)
            await self.planner.execute_scatter_gather(
                session_id, tool_calls, self._emit
            )

            # The planner has emitted ToolCallCompleted/Failed events.
            # The loop continues, which re-evaluates state including the new tool results.
