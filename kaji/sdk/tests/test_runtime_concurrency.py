"""Deterministic concurrency tests for session-scoped agent turns."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, cast

import pytest

from kaji.infra.events.schemas import AgentTurnFailed, UserMessage
from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.store.base import EventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents import (
    AgentBuilder,
    CancellationToken,
    InMemoryTurnCoordinator,
)
from kaji.runtime.agents.limits import TurnTimeoutError
from kaji.runtime.context import TurnContext
from kaji.runtime.determinism import Clock, IdScope, ScheduledCallback, TimerScheduler
from kaji.runtime.agents.coordinator import TurnCoordinator, TurnLease
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.types import GenerateResponse, ModelResponseChunk


class BarrierProvider:
    """Provider controlled by per-prompt entered/release barriers."""

    def __init__(self, sessions_by_prompt: Dict[str, str]) -> None:
        self._sessions_by_prompt = sessions_by_prompt
        self.entered = {prompt: asyncio.Event() for prompt in sessions_by_prompt}
        self.release = {prompt: asyncio.Event() for prompt in sessions_by_prompt}
        self.active_by_session: Dict[str, int] = defaultdict(int)
        self.max_active_by_session: Dict[str, int] = defaultdict(int)
        self.active_total = 0
        self.max_active_total = 0

    def active_for(self, session_id: str) -> int:
        return self.active_by_session[session_id]

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        prompt = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        )
        session_id = self._sessions_by_prompt[prompt]
        self.active_by_session[session_id] += 1
        self.max_active_by_session[session_id] = max(
            self.max_active_by_session[session_id],
            self.active_by_session[session_id],
        )
        self.active_total += 1
        self.max_active_total = max(self.max_active_total, self.active_total)
        self.entered[prompt].set()

        release_wait = asyncio.create_task(self.release[prompt].wait())
        cancellation_wait = (
            asyncio.create_task(cancellation_token.wait())
            if cancellation_token is not None
            else None
        )
        try:
            waits = {release_wait}
            if cancellation_wait is not None:
                waits.add(cancellation_wait)
            done, _ = await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
            if cancellation_wait is not None and cancellation_wait in done:
                raise asyncio.CancelledError()
            yield ModelResponseChunk(delta=f"reply:{prompt}")
        finally:
            release_wait.cancel()
            if cancellation_wait is not None:
                cancellation_wait.cancel()
            await asyncio.gather(
                release_wait,
                *(tuple([cancellation_wait]) if cancellation_wait is not None else ()),
                return_exceptions=True,
            )
            self.active_by_session[session_id] -= 1
            self.active_total -= 1


class ImmediateProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        *_args: Any,
        **_kwargs: Any,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.calls += 1
        prompt = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        )
        yield ModelResponseChunk(delta=f"reply:{prompt}")


class ManualClock(Clock):
    def __init__(self, monotonic: float = 10.0, wall: float = 1_700_000_000.0):
        self.monotonic = monotonic
        self.wall = wall

    def now_wall_seconds(self) -> float:
        return self.wall

    def now_monotonic(self) -> float:
        return self.monotonic


@dataclass
class _ManualTimer(ScheduledCallback):
    due: float
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler(TimerScheduler):
    def __init__(self, clock: ManualClock) -> None:
        self.clock = clock
        self.timers: list[_ManualTimer] = []

    @property
    def active_count(self) -> int:
        return sum(not timer.cancelled for timer in self.timers)

    def call_later(
        self, delay_seconds: float, callback: Callable[[], None]
    ) -> ScheduledCallback:
        timer = _ManualTimer(self.clock.monotonic + delay_seconds, callback)
        self.timers.append(timer)
        return timer

    def advance(self, seconds: float) -> None:
        self.clock.monotonic += seconds
        for timer in list(self.timers):
            if not timer.cancelled and timer.due <= self.clock.monotonic:
                timer.cancelled = True
                timer.callback()


class ScopedIds:
    def __init__(self) -> None:
        self._counts: Dict[IdScope, int] = defaultdict(int)

    def next(self, scope: IdScope) -> str:
        self._counts[scope] += 1
        return f"{scope}-{self._counts[scope]}"


def _build(provider: Any, coordinator: TurnCoordinator):
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder().provider(provider).coordinator(coordinator).build(store=store)
    )
    return runtime, store


class ObservedCoordinator:
    """Signals after each public acquisition attempt reaches the delegate."""

    def __init__(self) -> None:
        self.delegate = InMemoryTurnCoordinator()
        self.acquisitions = 0
        self.attempted: Dict[int, asyncio.Event] = defaultdict(asyncio.Event)

    def acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None = None,
        **options: Any,
    ) -> AbstractAsyncContextManager[TurnLease]:
        self.acquisitions += 1
        self.attempted[self.acquisitions].set()
        return self.delegate.acquire(session_id, cancellation_token, **options)

    async def quarantine(self, session_id: str) -> None:
        await self.delegate.quarantine(session_id)

    async def clear_quarantine(self, session_id: str) -> None:
        await self.delegate.clear_quarantine(session_id)


@pytest.mark.parametrize(
    ("deadline", "error_type"),
    [
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ],
)
def test_coordinator_rejects_invalid_deadlines(
    deadline: float, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type, match="deadline_monotonic"):
        InMemoryTurnCoordinator().acquire(
            "session",
            deadline_monotonic=deadline,
        )


@pytest.mark.asyncio
async def test_immediate_zero_deadline_records_one_queue_terminal_without_dispatch() -> (
    None
):
    clock = ManualClock()
    scheduler = ManualScheduler(clock)
    coordinator = InMemoryTurnCoordinator()
    provider = ImmediateProvider()
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(provider)
        .coordinator(coordinator)
        .clock(clock)
        .timer_scheduler(scheduler)
        .build(store=store)
    )

    with pytest.raises(TurnTimeoutError) as caught:
        await runtime.turn(
            "never dispatched",
            session_id="zero-deadline",
            context=TurnContext(deadline_monotonic=0),
        )

    assert caught.value.phase == "queue"
    events = await store.get_events("zero-deadline")
    failures = [event for event in events if isinstance(event, AgentTurnFailed)]
    assert len(failures) == 1
    assert failures[0].error_code == "TURN_TIMEOUT"
    assert failures[0].phase == "queue"
    assert failures[0].retryable is True
    assert failures[0].outcome == "not_started"
    assert provider.calls == 0
    assert coordinator.entry_count == 0
    assert coordinator.waiter_count == 0
    assert scheduler.active_count == 0


@pytest.mark.asyncio
async def test_queue_deadline_unlinks_waiter_and_cancellation_wins_same_tick() -> None:
    clock = ManualClock()
    scheduler = ManualScheduler(clock)
    coordinator = InMemoryTurnCoordinator()
    provider = BarrierProvider({"holder": "same"})
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(provider)
        .coordinator(coordinator)
        .clock(clock)
        .timer_scheduler(scheduler)
        .build(store=store)
    )
    holder = asyncio.create_task(runtime.turn("holder", session_id="same"))
    await provider.entered["holder"].wait()
    token = CancellationToken()
    waiting = asyncio.create_task(
        runtime.turn(
            "cancelled",
            session_id="same",
            cancellation_token=token,
            context=TurnContext(deadline_monotonic=clock.monotonic + 1),
        )
    )
    while coordinator.waiter_count != 1:
        await asyncio.sleep(0)
    scheduler.call_later(1, token.cancel)
    scheduler.advance(1)

    with pytest.raises(asyncio.CancelledError):
        await waiting
    failures = [
        event
        for event in await store.get_events("same")
        if event.type == EventType.AGENT_TURN_FAILED
    ]
    assert failures == []
    assert coordinator.waiter_count == 0
    provider.release["holder"].set()
    await holder
    assert coordinator.entry_count == 0
    assert scheduler.active_count == 0


@pytest.mark.asyncio
async def test_queued_deadline_records_once_and_preserves_fifo_third_waiter() -> None:
    clock = ManualClock()
    scheduler = ManualScheduler(clock)
    coordinator = InMemoryTurnCoordinator()
    provider = BarrierProvider({"first": "fifo", "expired": "fifo", "third": "fifo"})
    store = InMemoryEventStore()
    ids = ScopedIds()
    runtime = (
        AgentBuilder()
        .provider(provider)
        .coordinator(coordinator)
        .clock(clock)
        .timer_scheduler(scheduler)
        .id_factory(ids)
        .build(store=store)
    )

    first = asyncio.create_task(runtime.turn("first", session_id="fifo"))
    await provider.entered["first"].wait()
    expired = asyncio.create_task(
        runtime.turn(
            "expired",
            session_id="fifo",
            context=TurnContext(deadline_monotonic=clock.monotonic + 1),
        )
    )
    third = asyncio.create_task(runtime.turn("third", session_id="fifo"))
    while coordinator.waiter_count != 2:
        await asyncio.sleep(0)

    scheduler.advance(1)
    with pytest.raises(TurnTimeoutError) as caught:
        await expired
    assert caught.value.phase == "queue"
    assert not provider.entered["expired"].is_set()
    assert not provider.entered["third"].is_set()
    assert coordinator.waiter_count == 1

    failures = [
        event
        for event in await store.get_events("fifo")
        if event.type == EventType.AGENT_TURN_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].phase == "queue"
    assert failures[0].turn_id == "turn-2"

    provider.release["first"].set()
    first_result = await first
    await provider.entered["third"].wait()
    provider.release["third"].set()
    third_result = await third
    assert first_result.turn_id == "turn-1"
    assert third_result.turn_id == "turn-3"
    assert len({first_result.turn_id, failures[0].turn_id, third_result.turn_id}) == 3
    assert third_result.text == "reply:third"
    assert provider.max_active_by_session["fifo"] == 1
    assert coordinator.entry_count == coordinator.waiter_count == 0
    assert scheduler.active_count == 0


@pytest.mark.asyncio
async def test_same_session_turns_serialize_and_keep_results_turn_scoped() -> None:
    coordinator = ObservedCoordinator()
    provider = BarrierProvider({"A": "same", "B": "same"})
    runtime, store = _build(provider, coordinator)

    first = asyncio.create_task(runtime.turn("A", session_id="same"))
    await provider.entered["A"].wait()
    second = asyncio.create_task(runtime.turn("B", session_id="same"))
    await coordinator.attempted[2].wait()

    assert provider.active_for("same") == 1
    assert not provider.entered["B"].is_set()

    provider.release["A"].set()
    await provider.entered["B"].wait()
    provider.release["B"].set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result.text == "reply:A"
    assert second_result.text == "reply:B"
    for result in (first_result, second_result):
        assert result.events
        assert [event.turn_id for event in result.events] == [result.turn_id] * len(
            result.events
        )

    events = await store.get_events("same")
    assert sum(event.type == EventType.SESSION_CREATED for event in events) == 1
    assert provider.max_active_by_session["same"] == 1
    assert coordinator.delegate.entry_count == 0


@pytest.mark.asyncio
async def test_different_sessions_overlap() -> None:
    coordinator = InMemoryTurnCoordinator()
    provider = BarrierProvider({"left": "left", "right": "right"})
    runtime, _ = _build(provider, coordinator)

    left = asyncio.create_task(runtime.turn("left", session_id="left"))
    right = asyncio.create_task(runtime.turn("right", session_id="right"))
    await asyncio.gather(
        provider.entered["left"].wait(), provider.entered["right"].wait()
    )

    assert provider.active_for("left") == 1
    assert provider.active_for("right") == 1
    assert provider.max_active_total == 2

    provider.release["left"].set()
    provider.release["right"].set()
    await asyncio.gather(left, right)
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_coordinator_is_fifo_and_removes_quiescent_entry() -> None:
    coordinator = ObservedCoordinator()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    order: List[str] = []

    async def operation(name: str) -> None:
        async with coordinator.acquire("fifo"):
            order.append(name)
            if name == "first":
                first_entered.set()
                await release_first.wait()

    first = asyncio.create_task(operation("first"))
    await first_entered.wait()
    second = asyncio.create_task(operation("second"))
    await coordinator.attempted[2].wait()
    third = asyncio.create_task(operation("third"))
    await coordinator.attempted[3].wait()
    release_first.set()

    await asyncio.gather(first, second, third)
    assert order == ["first", "second", "third"]
    assert coordinator.delegate.entry_count == 0


@pytest.mark.asyncio
async def test_cancellation_before_and_during_acquisition_cleans_up() -> None:
    coordinator = ObservedCoordinator()
    cancelled = CancellationToken()
    cancelled.cancel()

    with pytest.raises(asyncio.CancelledError):
        async with coordinator.acquire("cancelled", cancelled):
            pytest.fail("pre-cancelled acquisition must not run")
    assert coordinator.delegate.entry_count == 0

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold() -> None:
        async with coordinator.acquire("waiting"):
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold())
    await holder_entered.wait()
    waiting_token = CancellationToken()

    async def wait_for_lease() -> None:
        async with coordinator.acquire("waiting", waiting_token):
            pytest.fail("cancelled waiter must not acquire")

    waiter = asyncio.create_task(wait_for_lease())
    await coordinator.attempted[3].wait()
    waiting_token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release_holder.set()
    await holder
    assert coordinator.delegate.entry_count == 0


@pytest.mark.asyncio
async def test_many_cancelled_waiters_are_unlinked_before_holder_releases() -> None:
    coordinator = ObservedCoordinator()
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold() -> None:
        async with coordinator.acquire("cancel-many"):
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold())
    await holder_entered.wait()
    tokens = [CancellationToken() for _ in range(64)]

    async def wait_for_lease(token: CancellationToken) -> None:
        async with coordinator.acquire("cancel-many", token):
            pytest.fail("cancelled waiter unexpectedly acquired")

    waiters = [asyncio.create_task(wait_for_lease(token)) for token in tokens]
    await coordinator.attempted[len(tokens) + 1].wait()
    assert coordinator.delegate.waiter_count == len(tokens)

    for token in tokens:
        token.cancel()
    results = await asyncio.gather(*waiters, return_exceptions=True)

    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert coordinator.delegate.waiter_count == 0
    assert coordinator.delegate.entry_count == 1

    release_holder.set()
    await holder
    assert coordinator.delegate.entry_count == 0


@pytest.mark.asyncio
async def test_cancellation_while_held_emits_turn_event_and_releases() -> None:
    coordinator = InMemoryTurnCoordinator()
    provider = BarrierProvider({"cancel": "same"})
    runtime, _ = _build(provider, coordinator)
    token = CancellationToken()

    task = asyncio.create_task(
        runtime.turn("cancel", session_id="same", cancellation_token=token)
    )
    await provider.entered["cancel"].wait()
    token.cancel()
    result = await task

    assert any(
        event.type == EventType.CANCELLATION_COMPLETED for event in result.events
    )
    assert all(event.turn_id == result.turn_id for event in result.events)
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_provider_error_releases_session_for_next_turn() -> None:
    class FailOnceProvider(ImmediateProvider):
        def __init__(self) -> None:
            self.calls = 0

        async def generate_stream(
            self,
            messages: List[Dict[str, Any]],
            *_args: Any,
            **_kwargs: Any,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider boom with secret-token")
            async for chunk in super().generate_stream(messages):
                yield chunk

    coordinator = InMemoryTurnCoordinator()
    runtime, store = _build(FailOnceProvider(), coordinator)

    with pytest.raises(RuntimeError, match="provider boom with secret-token"):
        await runtime.turn("first", session_id="same")
    failed_events = [
        event
        for event in await store.get_events("same")
        if event.type == EventType.AGENT_TURN_FAILED
    ]
    assert len(failed_events) == 1
    failure = failed_events[0]
    assert isinstance(failure, AgentTurnFailed)
    assert failure.error == "Agent turn failed"
    assert "secret-token" not in failure.model_dump_json()
    assert failure.turn_id is not None
    assert all(
        event.turn_id == failure.turn_id for event in await store.get_events("same")
    )
    assert coordinator.entry_count == 0

    result = await runtime.turn("second", session_id="same")

    assert result.text == "reply:second"
    assert result.turn_id != failure.turn_id
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_terminal_failure_commit_does_not_replace_provider_error() -> None:
    original = RuntimeError("original provider failure")

    class FailingProvider(ImmediateProvider):
        async def generate_stream(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            raise original
            yield ModelResponseChunk(delta="unreachable")

    class FailingTerminalJournal(InMemoryEventJournal):
        async def commit(self, event: Any) -> Any:
            if event.type == EventType.AGENT_TURN_FAILED:
                raise RuntimeError("terminal failure commit failed")
            return await super().commit(event)

    store = InMemoryEventStore()
    coordinator = InMemoryTurnCoordinator()
    journal = FailingTerminalJournal(store)
    runtime = (
        AgentBuilder()
        .provider(FailingProvider())
        .coordinator(coordinator)
        .build(journal=journal)
    )

    with pytest.raises(RuntimeError) as raised:
        await runtime.turn("fail", session_id="failure-commit")

    assert raised.value is original
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_arbitrary_operation_error_releases_session_for_reacquisition() -> None:
    coordinator = InMemoryTurnCoordinator()
    original = RuntimeError("arbitrary operation failed")

    with pytest.raises(RuntimeError) as raised:
        async with coordinator.acquire("operation"):
            raise original
    assert raised.value is original
    assert coordinator.entry_count == 0

    reacquired = False
    async with coordinator.acquire("operation"):
        reacquired = True

    assert reacquired
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_parent_task_cancellation_wins_when_token_flips_concurrently() -> None:
    coordinator = InMemoryTurnCoordinator()
    provider = BarrierProvider({"race": "race"})
    runtime, store = _build(provider, coordinator)
    token = CancellationToken()

    task = asyncio.create_task(
        runtime.turn("race", session_id="race", cancellation_token=token)
    )
    await provider.entered["race"].wait()
    task.cancel()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    types = [event.type for event in await store.get_events("race")]
    assert EventType.CANCELLATION_COMPLETED not in types
    assert EventType.AGENT_TURN_FAILED not in types
    assert coordinator.entry_count == 0


@pytest.mark.asyncio
async def test_default_coordinator_is_shared_per_store_only() -> None:
    shared_store = InMemoryEventStore()
    shared_provider = BarrierProvider({"A": "shared", "B": "shared"})
    first_runtime = (
        AgentBuilder()
        .provider(cast(ModelProvider, shared_provider))
        .build(store=shared_store)
    )
    second_runtime = (
        AgentBuilder()
        .provider(cast(ModelProvider, shared_provider))
        .build(store=shared_store)
    )

    assert first_runtime.coordinator is second_runtime.coordinator
    shared_coordinator = first_runtime.coordinator
    assert isinstance(shared_coordinator, InMemoryTurnCoordinator)

    first = asyncio.create_task(first_runtime.turn("A", session_id="shared"))
    await shared_provider.entered["A"].wait()
    second = asyncio.create_task(second_runtime.turn("B", session_id="shared"))
    for _ in range(10):
        if shared_coordinator.waiter_count > 0:
            break
        await asyncio.sleep(0)

    assert shared_coordinator.waiter_count == 1
    assert not shared_provider.entered["B"].is_set()
    shared_provider.release["A"].set()
    await shared_provider.entered["B"].wait()
    shared_provider.release["B"].set()
    await asyncio.gather(first, second)

    shared_events = await shared_store.get_events("shared")
    assert sum(event.type == EventType.SESSION_CREATED for event in shared_events) == 1
    assert shared_provider.max_active_by_session["shared"] == 1
    assert shared_coordinator.entry_count == 0

    left_store = InMemoryEventStore()
    right_store = InMemoryEventStore()
    independent_provider = BarrierProvider({"left": "same", "right": "same"})
    left_runtime = (
        AgentBuilder()
        .provider(cast(ModelProvider, independent_provider))
        .build(store=left_store)
    )
    right_runtime = (
        AgentBuilder()
        .provider(cast(ModelProvider, independent_provider))
        .build(store=right_store)
    )

    assert left_runtime.coordinator is not right_runtime.coordinator
    left = asyncio.create_task(left_runtime.turn("left", session_id="same"))
    right = asyncio.create_task(right_runtime.turn("right", session_id="same"))
    await asyncio.gather(
        independent_provider.entered["left"].wait(),
        independent_provider.entered["right"].wait(),
    )
    assert independent_provider.active_for("same") == 2
    independent_provider.release["left"].set()
    independent_provider.release["right"].set()
    await asyncio.gather(left, right)


def test_non_weakref_store_requires_explicit_default_coordinator() -> None:
    class NonWeakStore:
        __slots__ = ("delegate",)

        def __init__(self) -> None:
            self.delegate = InMemoryEventStore()

        async def append(self, event: Any) -> Any:
            return await self.delegate.append(event)

        async def get_events(self, session_id: str, **kwargs: Any) -> Any:
            return await self.delegate.get_events(session_id, **kwargs)

        async def last_sequence(self, session_id: str) -> int:
            return await self.delegate.last_sequence(session_id)

    store = cast(EventStore, NonWeakStore())
    builder = AgentBuilder().provider(cast(ModelProvider, ImmediateProvider()))

    with pytest.raises(TypeError, match="inject a coordinator explicitly"):
        builder.build(store=store)

    coordinator = InMemoryTurnCoordinator()
    runtime = builder.coordinator(coordinator).build(store=store)
    assert runtime.coordinator is coordinator


@pytest.mark.asyncio
async def test_public_entry_points_acquire_once_and_builder_injects() -> None:
    coordinator = ObservedCoordinator()
    runtime, store = _build(ImmediateProvider(), coordinator)
    assert runtime.coordinator is coordinator

    await runtime.turn("turn", session_id="turn")
    await runtime.send("send", "send")
    await store.append(UserMessage(session_id="run", content="run"))
    await runtime.run_turn("run")

    assert coordinator.acquisitions == 3
    assert coordinator.delegate.entry_count == 0
