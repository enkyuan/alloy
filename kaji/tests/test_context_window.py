from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    AgentReasoningStarted,
    SessionClosed,
    SessionCreated,
    StoredKajiEvent,
    ToolApprovalApproved,
    ToolCallCompleted,
    ToolCallRequested,
    UserMessage,
    require_stored_event,
)
from kaji.runtime.sessions.replay import SessionState
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents.context import (
    ContextIntegrityError,
    ContextWindow,
    ContextWindowOverflowError,
    ToolInvocation,
    TurnContext,
    build_context,
)
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderResponseLimits,
)
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.tools.registry import ToolSpec


def _stored(event: Any) -> StoredKajiEvent:
    return require_stored_event(event)


def test_projector_applies_ten_thousand_tool_events_once() -> None:
    projector = SessionProjector("projection-10k")
    sequence = 0

    def apply(event: Any) -> None:
        nonlocal sequence
        sequence += 1
        projector.apply(_stored(event.model_copy(update={"sequence": sequence})))

    for batch in range(2_000):
        call_id = f"call-{batch}"
        apply(UserMessage(session_id="projection-10k", content=str(batch)))
        apply(AgentReasoningStarted(session_id="projection-10k"))
        apply(
            ToolCallRequested(
                session_id="projection-10k",
                turn_id=f"turn-{batch}",
                tool_name="lookup",
                tool_call_id=call_id,
                tool_args={"batch": batch},
            )
        )
        apply(
            ToolCallCompleted(
                session_id="projection-10k",
                turn_id=f"turn-{batch}",
                tool_name="lookup",
                tool_call_id=call_id,
                result={"ok": True},
            )
        )
        apply(
            AgentMessageCompleted(
                session_id="projection-10k",
                content=f"done-{batch}",
            )
        )

    assert projector.cursor == 10_000
    assert projector.applied_events == 10_000
    snapshot = projector.state
    assert len(snapshot.messages) == 8_000
    assert snapshot.messages[-1]["content"] == "done-1999"
    assert projector.context_index_stats.cold_events == 10_000
    assert projector.context_index_stats.scanned_tool_calls == 2_000
    assert projector.context_index_stats.persistent_copied_payload_bytes == 0


def test_projection_separates_batches_and_groups_parallel_calls() -> None:
    projector = SessionProjector("batches")
    events = [
        UserMessage(session_id="batches", content="go", sequence=1),
        AgentReasoningStarted(session_id="batches", sequence=2),
        ToolCallRequested(
            session_id="batches",
            turn_id="turn-1",
            tool_name="one",
            tool_call_id="c1",
            tool_args={},
            sequence=3,
        ),
        ToolCallRequested(
            session_id="batches",
            turn_id="turn-1",
            tool_name="two",
            tool_call_id="c2",
            tool_args={},
            sequence=4,
        ),
        ToolCallCompleted(
            session_id="batches",
            turn_id="turn-1",
            tool_name="one",
            tool_call_id="c1",
            result=1,
            sequence=5,
        ),
        ToolCallCompleted(
            session_id="batches",
            turn_id="turn-1",
            tool_name="two",
            tool_call_id="c2",
            result=2,
            sequence=6,
        ),
        AgentReasoningStarted(session_id="batches", sequence=7),
        ToolCallRequested(
            session_id="batches",
            turn_id="turn-2",
            tool_name="three",
            tool_call_id="c3",
            tool_args={},
            sequence=8,
        ),
        ToolCallCompleted(
            session_id="batches",
            turn_id="turn-2",
            tool_name="three",
            tool_call_id="c3",
            result=3,
            sequence=9,
        ),
    ]
    for event in events:
        projector.apply(_stored(event))

    assistants = [
        message
        for message in projector.state.messages
        if message["role"] == "assistant"
    ]
    assert [
        [call["id"] for call in message["tool_calls"]] for message in assistants
    ] == [["c1", "c2"], ["c3"]]


def test_projector_rejects_mixed_sessions_and_non_contiguous_sequences() -> None:
    projector = SessionProjector("s1")
    projector.apply(_stored(UserMessage(session_id="s1", content="one", sequence=1)))

    with pytest.raises(ValueError, match="mixed sessions"):
        projector.apply(
            _stored(UserMessage(session_id="s2", content="two", sequence=2))
        )
    with pytest.raises(ValueError, match="expected sequence 2"):
        projector.apply(
            _stored(UserMessage(session_id="s1", content="three", sequence=3))
        )


def test_context_window_keeps_complete_current_tool_group() -> None:
    state = SessionState(
        session_id="context",
        messages=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "bye"},
            {"role": "user", "content": "current"},
            {
                "role": "assistant",
                "content": "checking",
                "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {}}],
            },
            {
                "role": "tool",
                "name": "lookup",
                "content": "done",
                "tool_call_id": "call-1",
            },
        ],
    )

    result = build_context(
        state,
        SystemPrompt("system"),
        window=ContextWindow(max_turns=1, max_characters=100),
    )

    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert result.messages[2]["tool_calls"][0]["id"] == "call-1"
    assert result.messages[3]["tool_call_id"] == "call-1"
    assert result.diagnostics.dropped_turns == 1
    assert result.diagnostics.dropped_messages == 2
    assert result.diagnostics.dropped_characters == 6


def test_context_window_rejects_user_while_tool_call_is_pending() -> None:
    state = SessionState(
        session_id="interleaved",
        messages=[
            {"role": "user", "content": "ancient"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "lookup",
                        "arguments": {"nested": {"value": "original"}},
                    }
                ],
            },
            {"role": "user", "content": "interrupt"},
            {
                "role": "tool",
                "name": "lookup",
                "content": "result",
                "tool_call_id": "call-1",
            },
        ],
    )

    with pytest.raises(ContextIntegrityError, match="user message.*pending"):
        build_context(
            state,
            SystemPrompt("system"),
            window=ContextWindow(max_turns=1, max_characters=1_000),
        )


def test_context_window_rejects_unmatched_current_tool_request() -> None:
    state = SessionState(
        session_id="pending-current",
        messages=[
            {"role": "user", "content": "start"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "lookup", "arguments": {}}],
            },
        ],
    )

    with pytest.raises(ContextIntegrityError, match="matching results"):
        build_context(state, SystemPrompt("system"))


def test_context_window_rejects_orphan_tool_results() -> None:
    state = SessionState(
        session_id="orphan",
        messages=[
            {
                "role": "tool",
                "name": "lookup",
                "content": "result",
                "tool_call_id": "missing",
            }
        ],
    )

    with pytest.raises(ContextIntegrityError, match="Orphan tool result"):
        build_context(state, SystemPrompt("system"))


def test_context_window_drops_whole_turns_by_character_limit() -> None:
    state = SessionState(
        session_id="characters",
        messages=[
            {"role": "user", "content": "1234"},
            {"role": "assistant", "content": "5678"},
            {"role": "user", "content": "12345"},
        ],
    )

    result = build_context(
        state,
        SystemPrompt("system"),
        window=ContextWindow(max_turns=None, max_characters=5),
    )

    assert [message["content"] for message in result.messages[1:]] == ["12345"]
    assert result.diagnostics.dropped_turns == 1
    assert result.diagnostics.dropped_messages == 2
    assert result.diagnostics.dropped_characters == 8


def test_context_window_rejects_current_turn_overflow() -> None:
    state = SessionState(
        session_id="overflow",
        messages=[
            {"role": "user", "content": "12345"},
            {"role": "assistant", "content": "67"},
        ],
    )

    with pytest.raises(ContextWindowOverflowError) as caught:
        build_context(
            state,
            SystemPrompt("system"),
            window=ContextWindow(max_turns=1, max_characters=6),
        )

    assert caught.value.current_turn_characters == 7
    assert caught.value.max_characters == 6


def test_context_window_counts_structured_tool_payloads() -> None:
    state = SessionState(session_id="structured")
    old_turn = [
        {"role": "user", "content": "old"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c",
                    "name": "lookup",
                    "arguments": {"query": "xxxxxxxxxx"},
                }
            ],
        },
        {
            "role": "tool",
            "content": "ok",
            "name": "lookup",
            "tool_call_id": "c",
        },
    ]
    state.messages.extend([*old_turn, {"role": "user", "content": "now"}])

    result = build_context(
        state,
        SystemPrompt("system"),
        window=ContextWindow(max_turns=None, max_characters=10),
    )

    assert [message["content"] for message in result.messages[1:]] == ["now"]
    assert result.diagnostics.dropped_characters == 41

    state.messages[:] = [
        {"role": "user", "content": "now"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c",
                    "name": "n",
                    "arguments": {"payload": "abcdefghij"},
                }
            ],
        },
        {
            "role": "tool",
            "content": "",
            "name": "n",
            "tool_call_id": "c",
        },
    ]
    with pytest.raises(ContextWindowOverflowError) as caught:
        build_context(
            state,
            SystemPrompt("system"),
            window=ContextWindow(max_turns=None, max_characters=30),
        )
    assert caught.value.current_turn_characters == 31


class _CountingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[tuple[str, int, int | None]] = []

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        self.reads.append((session_id, after_sequence, limit))
        return await super().get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )


class _TenIterationProvider(ModelProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        yield ModelResponseChunk(
            tool_calls=[
                {
                    "id": f"call-{self.calls}",
                    "name": "noop",
                    "arguments": {},
                }
            ]
        )


class _ExternalAppendProvider(ModelProvider):
    def __init__(self, store: InMemoryEventStore) -> None:
        self.store = store

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        await self.store.append(
            ToolApprovalApproved(
                session_id="interleave",
                turn_id="approval-bridge",
                tool_name="noop",
                tool_call_id="approval-call",
            )
        )
        yield ModelResponseChunk(delta="done")


class _TextProvider(ModelProvider):
    def __init__(self, text: str) -> None:
        self.text = text
        self.seen_messages: List[Dict[str, Any]] = []

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> GenerateResponse:
        return GenerateResponse(text=self.text)

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.seen_messages = messages
        yield ModelResponseChunk(delta=self.text)


class _RagChunk:
    def __init__(self, text: str) -> None:
        self.text = text


class _RecordingRag:
    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []

    async def retrieve(self, query: str, *, top_k: int) -> list[_RagChunk]:
        self.queries.append((query, top_k))
        return [_RagChunk("grounded fact")]


def _ownership_values(messages: List[Dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for message in messages:
        for call in message.get("tool_calls", ()):
            if call.get("id") == "ownership-call":
                values.append(call["arguments"]["nested"]["value"])
    return values


class _OwnershipProvider(_TextProvider):
    def __init__(self) -> None:
        super().__init__("done")
        self.calls = 0
        self.observed: list[str] = []

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        if self.calls == 1:
            yield ModelResponseChunk(
                tool_calls=[
                    {
                        "id": "ownership-call",
                        "name": "ownership",
                        "arguments": {"nested": {"value": "original"}},
                    }
                ]
            )
            return

        values = _ownership_values(messages)
        self.observed.extend(values)
        if self.calls == 2:
            for message in messages:
                for call in message.get("tool_calls", ()):
                    if call.get("id") == "ownership-call":
                        call["arguments"]["nested"]["value"] = "provider-mutated"
            messages.clear()
        yield ModelResponseChunk(delta=self.text)


class _OwnershipCaptureProvider(_TextProvider):
    def __init__(self) -> None:
        super().__init__("captured")
        self.observed: list[str] = []

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
        response_limits: ProviderResponseLimits | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.observed.extend(_ownership_values(messages))
        yield ModelResponseChunk(delta=self.text)


@pytest.mark.asyncio
async def test_runtime_reads_one_cursor_suffix_per_ten_iteration_turn() -> None:
    store = _CountingStore()
    provider = _TenIterationProvider()
    spec = ToolSpec(
        name="noop",
        description="No operation",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )

    async def execute(_invocation: ToolInvocation) -> Dict[str, Any]:
        return {"ok": True}

    runtime = AgentRuntime(
        store=store,
        provider=provider,
        planner=ToolPlanner(executor=execute, specs={"noop": spec}),
        tools=[spec],
        strategy=AgentStrategy(max_iterations=10),
        default_context=TurnContext(principal_id="test-principal"),
    )
    await store.append(SessionCreated(session_id="runtime"))
    await store.append(UserMessage(session_id="runtime", content="first"))
    store.reads.clear()

    await runtime.run_turn("runtime")

    assert provider.calls == 10
    assert store.reads == [("runtime", 0, None)]

    cached_cursor = await store.last_sequence("runtime")
    await store.append(UserMessage(session_id="runtime", content="second"))
    store.reads.clear()
    await runtime.run_turn("runtime")

    assert provider.calls == 20
    assert store.reads == [("runtime", cached_cursor, None)]


@pytest.mark.asyncio
async def test_runtime_resyncs_external_sequence_gap() -> None:
    store = _CountingStore()
    runtime = AgentRuntime(
        store=store,
        provider=_ExternalAppendProvider(store),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )
    await store.append(SessionCreated(session_id="interleave"))
    await store.append(UserMessage(session_id="interleave", content="go"))
    store.reads.clear()

    await runtime.run_turn("interleave")

    # Cold sync applies 1-2. Reasoning is sequence 3, the bridge writes 4,
    # and the runtime's delta at 5 detects and pulls exactly the missing suffix.
    assert store.reads == [
        ("interleave", 0, None),
        ("interleave", 3, None),
    ]
    assert [event.sequence for event in await store.get_events("interleave")] == list(
        range(1, 7)
    )


async def _unused_executor() -> Dict[str, Any]:
    return {}


@pytest.mark.asyncio
async def test_turn_result_needs_no_second_history_read() -> None:
    store = _CountingStore()
    runtime = AgentRuntime(
        store=store,
        provider=_TextProvider("answer"),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )

    result = await runtime.turn("question", session_id="result")

    assert result.text == "answer"
    assert store.reads == [("result", 0, None)]
    assert [event.sequence for event in result.events] == list(range(1, 6))


@pytest.mark.asyncio
async def test_separate_runtime_caches_resume_from_their_own_cursor() -> None:
    store = _CountingStore()
    runtime_a = AgentRuntime(
        store=store,
        provider=_TextProvider("a"),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )
    runtime_b = AgentRuntime(
        store=store,
        provider=_TextProvider("b"),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )
    await store.append(SessionCreated(session_id="shared"))
    await store.append(UserMessage(session_id="shared", content="first"))
    await runtime_a.run_turn("shared")
    cursor_a = await store.last_sequence("shared")

    await store.append(UserMessage(session_id="shared", content="second"))
    await runtime_b.run_turn("shared")
    await store.append(UserMessage(session_id="shared", content="third"))
    store.reads.clear()

    await runtime_a.run_turn("shared")

    assert store.reads == [("shared", cursor_a, None)]


@pytest.mark.asyncio
async def test_runtime_exposes_context_drop_diagnostics() -> None:
    store = _CountingStore()
    provider = _TextProvider("new")
    runtime = AgentRuntime(
        store=store,
        provider=provider,
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
        context_window=ContextWindow(max_turns=1, max_characters=100),
    )
    await store.append(SessionCreated(session_id="diagnostics"))
    await store.append(UserMessage(session_id="diagnostics", content="old"))
    await store.append(AgentMessageCompleted(session_id="diagnostics", content="bye"))
    await store.append(UserMessage(session_id="diagnostics", content="current"))

    await runtime.run_turn("diagnostics")

    assert [message["role"] for message in provider.seen_messages] == [
        "system",
        "user",
    ]
    diagnostics = runtime.context_diagnostics("diagnostics")
    assert diagnostics is not None
    assert diagnostics.dropped_turns == 1
    assert diagnostics.dropped_messages == 2
    assert diagnostics.dropped_characters == 6


@pytest.mark.asyncio
async def test_runtime_rag_reads_latest_user_from_projection_index() -> None:
    store = InMemoryEventStore()
    provider = _TextProvider("answer")
    rag = _RecordingRag()
    runtime = AgentRuntime(
        store=store,
        provider=provider,
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
        rag=rag,
        rag_top_k=3,
    )

    await runtime.turn("indexed question", session_id="rag")

    assert rag.queries == [("indexed question", 3)]
    assert provider.seen_messages[0]["content"].startswith("## Relevant context")
    assert runtime._projectors["rag"].context_index_stats.latest_user_accesses == 1


@pytest.mark.asyncio
async def test_runtime_exposes_context_index_stats_without_creating_projectors() -> (
    None
):
    store = InMemoryEventStore()
    runtime = AgentRuntime(
        store=store,
        provider=_TextProvider("answer"),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )

    assert runtime.projection_cache_size == 0
    assert runtime.context_index_stats("missing") is None
    assert runtime.projection_cache_size == 0

    await runtime.turn("indexed question", session_id="stats")
    stats = runtime.context_index_stats("stats")
    assert stats is not None
    assert stats.full_cold_builds == 1
    assert stats.suffix_calls == 1
    with pytest.raises(FrozenInstanceError):
        setattr(stats, "suffix_calls", 999)
    repeated = runtime.context_index_stats("stats")
    assert repeated == stats
    assert repeated is not stats


@pytest.mark.asyncio
async def test_projection_and_diagnostics_caches_follow_store_capacity() -> None:
    store = InMemoryEventStore(max_sessions=2)
    runtime = AgentRuntime(
        store=store,
        provider=_TextProvider("unused"),
        planner=ToolPlanner(executor=lambda _invocation: _unused_executor()),
    )

    for index in range(5):
        session_id = f"closed-{index}"
        await runtime.turn("go", session_id=session_id)
        await runtime.append_event(SessionClosed(session_id=session_id))

    assert runtime.projection_cache_size == 2
    assert len(runtime._context_diagnostics) <= 2


@pytest.mark.asyncio
async def test_mutations_cannot_cross_store_projection_or_result_boundaries() -> None:
    store = InMemoryEventStore()
    spec = ToolSpec(
        name="ownership",
        description="Ownership probe",
        parameters={"type": "object"},
        risk="read",
    )

    async def execute(_invocation: ToolInvocation) -> Dict[str, Any]:
        return {"ok": True}

    provider_a = _OwnershipProvider()
    runtime_a = AgentRuntime(
        store=store,
        provider=provider_a,
        planner=ToolPlanner(executor=execute, specs={spec.name: spec}),
        tools=[spec],
        default_context=TurnContext(principal_id="test-principal"),
    )
    provider_b = _OwnershipCaptureProvider()
    runtime_b = AgentRuntime(
        store=store,
        provider=provider_b,
        planner=ToolPlanner(executor=execute, specs={spec.name: spec}),
        tools=[spec],
        default_context=TurnContext(principal_id="test-principal"),
    )

    result = await runtime_a.turn("go", session_id="ownership")
    event_request = next(
        event for event in result.events if event.type == EventType.TOOL_CALL_REQUESTED
    )
    tool_request = result.tool_call_events[0]
    event_request.tool_args["nested"]["value"] = "caller-event-mutated"
    assert tool_request.tool_args["nested"]["value"] == "original"
    tool_request.tool_args["nested"]["value"] = "caller-tool-mutated"

    persisted = await store.get_events("ownership")
    persisted_request = next(
        event for event in persisted if event.type == EventType.TOOL_CALL_REQUESTED
    )
    assert persisted_request.tool_args["nested"]["value"] == "original"

    await runtime_a.send("ownership", "again")
    await runtime_b.send("ownership", "other runtime")

    assert provider_a.observed == ["original", "original"]
    assert provider_b.observed == ["original"]
    persisted_again = await store.get_events("ownership")
    request_again = next(
        event
        for event in persisted_again
        if event.type == EventType.TOOL_CALL_REQUESTED
    )
    assert request_again.tool_args["nested"]["value"] == "original"
