"""Deterministic operation-count gates for production-beta runtime bounds."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest

from kaji.infra.events.errors import EventBufferOverflowError
from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    NewKajiEvent,
    SessionCreated,
    StoredKajiEvent,
    UserMessage,
    require_stored_event,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.store.base import AppendResult
from kaji.infra.observability.protocols import Measurement
from kaji.runtime.agents import CancellationToken, InMemoryTurnCoordinator
from kaji.runtime.agents.context import (
    ContextWindow,
    ContextWindowOverflowError,
    TurnContext,
    build_context,
)
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.determinism import Clock, IdScope
from kaji.runtime.providers.types import GenerateResponse, ModelResponseChunk
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.tools.idempotency import InMemoryToolIdempotencyLedger
from kaji.runtime.tools.registry import ToolSpec


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def next(self, scope: IdScope) -> str:
        self.value += 1
        return f"{scope}-{self.value}"


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now_wall_seconds(self) -> float:
        return self.value

    def now_monotonic(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def __call__(self) -> float:
        return self.value


class _CountingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[tuple[str, int, int | None]] = []
        self.inserted_ids: list[str] = []

    async def append(self, event: NewKajiEvent) -> AppendResult:
        result = await super().append(event)
        if result.inserted:
            self.inserted_ids.append(result.event.id)
        return result

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


class _Metrics:
    def __init__(self) -> None:
        self.max_subscriber_depth = 0

    def record(self, measurement: Measurement) -> None:
        if measurement.name == "kaji.subscriber.lag_events":
            self.max_subscriber_depth = max(
                self.max_subscriber_depth, int(measurement.value)
            )


def test_runtime_clock_seam_accepts_clock_protocol_only() -> None:
    assert AgentRuntime.__init__.__annotations__["clock"] == Clock | None


class _ToolLoopProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self, *_args: Any, **_kwargs: Any
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


async def _spin_until(predicate: Callable[[], bool], *, attempts: int = 10_000) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("deterministic barrier was not reached")


@pytest.mark.asyncio
@pytest.mark.parametrize("iterations", [1, 5, 10])
async def test_tool_iterations_have_one_initial_suffix_read_and_one_apply_per_insert(
    iterations: int,
) -> None:
    ids = _Ids()
    clock = _Clock()
    store = _CountingStore()
    provider = _ToolLoopProvider()
    spec = ToolSpec(
        name="noop",
        description="no operation",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )

    async def execute(_invocation: Any) -> dict[str, bool]:
        return {"ok": True}

    planner = ToolPlanner(
        execute,
        specs={spec.name: spec},
        id_factory=ids,
        clock=clock,
    )
    runtime = AgentRuntime(
        bus=None,
        store=store,
        provider=provider,
        planner=planner,
        tools=[spec],
        strategy=AgentStrategy(max_iterations=iterations),
        default_context=TurnContext(principal_id="complexity", id_factory=ids),
        id_factory=ids,
        clock=clock,
    )
    await store.append(
        SessionCreated(id="seed-session", timestamp=0, session_id="complexity")
    )
    await store.append(
        UserMessage(id="seed-user", timestamp=0, session_id="complexity", content="go")
    )
    store.reads.clear()

    await runtime.run_turn("complexity")

    assert provider.calls == iterations
    assert store.reads == [("complexity", 0, None)]
    assert len(store.inserted_ids) == len(set(store.inserted_ids))
    last_sequence = await store.last_sequence("complexity")
    observed = SessionProjector("complexity")
    assert await observed.sync(store) == last_sequence
    assert observed.cursor == last_sequence
    assert observed.applied_events == last_sequence == len(store.inserted_ids)
    assert await observed.sync(store) == 0
    assert observed.applied_events == last_sequence


class _BarrierProvider:
    def __init__(self, target: int) -> None:
        self.target = target
        self.entered = 0
        self.active = 0
        self.peak = 0
        self.barrier = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="ok")

    async def generate_stream(
        self, *_args: Any, **_kwargs: Any
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.entered += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.entered == self.target:
            self.barrier.set()
        try:
            await self.release.wait()
            yield ModelResponseChunk(delta="ok")
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_same_session_25_serializes_while_two_sessions_overlap() -> None:
    same_coordinator = InMemoryTurnCoordinator()
    same_provider = _BarrierProvider(target=1)
    same_runtime = AgentRuntime(
        bus=None,
        store=InMemoryEventStore(),
        provider=same_provider,
        coordinator=same_coordinator,
        id_factory=_Ids(),
        clock=_Clock(),
    )
    same = [
        asyncio.create_task(same_runtime.turn(f"same-{index}", session_id="same"))
        for index in range(25)
    ]
    await same_provider.barrier.wait()
    await _spin_until(lambda: same_coordinator.waiter_count == 24)
    assert same_provider.peak == 1
    same_provider.release.set()
    await asyncio.gather(*same)
    assert same_provider.peak == 1
    assert same_coordinator.entry_count == same_coordinator.waiter_count == 0

    cross_coordinator = InMemoryTurnCoordinator()
    cross_provider = _BarrierProvider(target=2)
    cross_runtime = AgentRuntime(
        bus=None,
        store=InMemoryEventStore(),
        provider=cross_provider,
        coordinator=cross_coordinator,
        id_factory=_Ids(),
        clock=_Clock(),
    )
    left = asyncio.create_task(cross_runtime.turn("left", session_id="left"))
    right = asyncio.create_task(cross_runtime.turn("right", session_id="right"))
    await cross_provider.barrier.wait()
    assert cross_provider.peak == 2
    cross_provider.release.set()
    await asyncio.gather(left, right)
    assert cross_coordinator.entry_count == cross_coordinator.waiter_count == 0


async def _run_tool_batch(*, parallel_safe: bool, count: int) -> tuple[int, list[str]]:
    active = 0
    entered = 0
    peak = 0
    target = 4 if parallel_safe else 1
    barrier = asyncio.Event()
    release = asyncio.Event()

    async def execute(_invocation: Any) -> dict[str, bool]:
        nonlocal active, entered, peak
        entered += 1
        active += 1
        peak = max(peak, active)
        if entered == target:
            barrier.set()
        try:
            await release.wait()
            return {"ok": True}
        finally:
            active -= 1

    spec = ToolSpec(
        name="batch",
        description="bounded batch",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
        parallel_safe=parallel_safe,
    )
    planner = ToolPlanner(
        execute, specs={spec.name: spec}, id_factory=_Ids(), clock=_Clock()
    )

    async def emit(_event: Any) -> None:
        return None

    pending = asyncio.create_task(
        planner.execute_batch(
            "tools",
            [
                {"id": f"call-{index}", "name": spec.name, "arguments": {}}
                for index in range(count)
            ],
            emit,
            turn_id="turn",
            turn_context=TurnContext(
                principal_id="complexity", request_id="request", trace_id="trace"
            ),
            cancellation_token=CancellationToken(),
        )
    )
    await barrier.wait()
    assert peak == target
    release.set()
    await pending
    return peak, await planner.controller.drain_tools(0)


@pytest.mark.asyncio
async def test_tool_batches_respect_parallel_and_exclusive_bounds() -> None:
    parallel_peak, parallel_stuck = await _run_tool_batch(parallel_safe=True, count=100)
    exclusive_peak, exclusive_stuck = await _run_tool_batch(
        parallel_safe=False, count=25
    )
    assert parallel_peak == 4
    assert exclusive_peak == 1
    assert parallel_stuck == exclusive_stuck == []


@pytest.mark.asyncio
async def test_ledger_fake_clock_evicts_only_eligible_completed_entries() -> None:
    clock = _Clock()
    ledger = InMemoryToolIdempotencyLedger(
        max_entries=5, completed_ttl_seconds=10, clock=clock
    )
    for index in range(5):
        claim = await ledger.claim(
            session_id="ledger",
            tool_call_id=f"call-{index}",
            tool_name="tool",
            tool_args={},
        )
        assert claim.kind == "owner"
        await ledger.complete(claim, {"ok": True})
    assert ledger.size == 5

    clock.advance(10)
    replacement = await ledger.claim(
        session_id="ledger",
        tool_call_id="replacement",
        tool_name="tool",
        tool_args={},
    )
    assert replacement.kind == "owner"
    assert ledger.size == 1


@pytest.mark.asyncio
async def test_subscriber_capacity_1024_overflows_once_and_cursor_resume_is_lossless() -> (
    None
):
    metrics = _Metrics()
    journal = InMemoryEventJournal(
        subscriber_queue_capacity=1_024, metrics_sink=metrics
    )
    subscription = await journal.open_subscription("slow")
    for index in range(1_024):
        await journal.commit(
            UserMessage(
                id=f"event-{index}",
                timestamp=0,
                session_id="slow",
                content=str(index),
            )
        )
    assert metrics.max_subscriber_depth == 1_024

    last = await journal.commit(
        UserMessage(
            id="event-overflow",
            timestamp=0,
            session_id="slow",
            content="overflow",
        )
    )
    with pytest.raises(EventBufferOverflowError) as caught:
        await anext(subscription)
    assert caught.value.last_sequence == 0
    assert caught.value.latest_sequence == last.sequence == 1_025

    replayed: list[int] = []
    cursor = caught.value.last_sequence
    while cursor < caught.value.latest_sequence:
        page = await journal.store.get_events("slow", after_sequence=cursor, limit=128)
        replayed.extend(event.sequence for event in page if event.sequence is not None)
        cursor = replayed[-1]
    assert replayed == list(range(1, 1_026))

    resumed = await journal.open_subscription("slow", after_sequence=cursor)
    next_event = await journal.commit(
        UserMessage(
            id="event-resumed",
            timestamp=0,
            session_id="slow",
            content="resumed",
        )
    )
    assert await anext(resumed) == next_event
    await resumed.aclose()


def test_context_retains_only_complete_turns_within_public_defaults() -> None:
    projector = SessionProjector("context")
    sequence = 0
    for index in range(40):
        for event in (
            UserMessage(session_id="context", content="u" * 1_500),
            AgentMessageCompleted(session_id="context", content="a" * 1_500),
        ):
            sequence += 1
            projector.apply(
                require_stored_event(event.model_copy(update={"sequence": sequence}))
            )

    result = build_context(
        projector.state, SystemPrompt("system"), window=ContextWindow()
    )
    retained = result.messages[1:]
    assert len(retained) % 2 == 0
    assert len(retained) // 2 <= 32
    assert sum(len(message["content"]) for message in retained) <= 100_000
    assert retained[0]["role"] == "user"
    assert retained[-1]["role"] == "assistant"


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        self.calls += 1
        return GenerateResponse(text="unexpected")

    async def generate_stream(
        self, *_args: Any, **_kwargs: Any
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        yield ModelResponseChunk(delta="unexpected")


@pytest.mark.asyncio
async def test_current_turn_character_overflow_fails_before_provider_invocation() -> (
    None
):
    provider = _CountingProvider()
    coordinator = InMemoryTurnCoordinator()
    runtime = AgentRuntime(
        bus=None,
        store=InMemoryEventStore(),
        provider=provider,
        coordinator=coordinator,
        context_window=ContextWindow(max_turns=32, max_characters=100_000),
        id_factory=_Ids(),
        clock=_Clock(),
    )

    with pytest.raises(ContextWindowOverflowError):
        await runtime.turn("x" * 100_001, session_id="overflow")

    assert provider.calls == 0
    assert coordinator.entry_count == coordinator.waiter_count == 0
