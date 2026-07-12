from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterator
from dataclasses import fields
import math
from types import SimpleNamespace
from typing import Any, Literal, Never

import pytest

from kaji.infra.events.store.inmem import InMemoryEventStore
from kaji.infra.events.replay import replay_session
from kaji.infra.events.types import EventType
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.coordinator import InMemoryTurnCoordinator
from kaji.runtime.agents.context import (
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.tools.execution import (
    ToolExecutionController,
    ToolExecutionError,
    ToolExecutionLimits,
)
from kaji.runtime.tools.errors import ToolArgumentValidationError
from kaji.runtime.tools.idempotency import (
    IdempotencyCapacityExceeded,
    IdempotencyConflictError,
    InMemoryToolIdempotencyLedger,
    ToolIdempotencyClaim,
    ToolIdempotencyFailure,
)
from kaji.runtime.tools.registry import ToolSpec
from kaji.runtime.providers.types import GenerateResponse, ModelResponseChunk
from tests.helpers.mock_provider import MockProvider


async def _claim(
    ledger: InMemoryToolIdempotencyLedger,
    call_id: str,
    *,
    session_id: str = "session",
    arguments: dict[str, Any] | None = None,
):
    return await ledger.claim(
        session_id=session_id,
        tool_call_id=call_id,
        tool_name="tool",
        tool_args=arguments or {},
    )


def _invocation(
    call_id: str,
    *,
    session_id: str = "session",
    token: CancellationToken | None = None,
    arguments: dict[str, Any] | None = None,
) -> ToolInvocation:
    return ToolInvocation(
        name="tool",
        arguments=arguments or {},
        context=ToolExecutionContext(
            principal_id="principal",
            session_id=session_id,
            turn_id="turn",
            request_id="request",
            trace_id="trace",
            tool_call_id=call_id,
            idempotency_key=f"{session_id}:{call_id}",
            cancellation_token=token or CancellationToken(),
            deadline_monotonic=None,
            db=None,
            metadata={},
        ),
    )


async def _noop_started() -> None:
    return None


async def _wait_until(predicate, *, timeout: float = 1) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_ledger_coalesces_replays_and_detaches_results() -> None:
    ledger = InMemoryToolIdempotencyLedger()
    owner = await _claim(ledger, "call")
    waiter = await _claim(ledger, "call")
    assert owner.kind == "owner"
    assert waiter.kind == "waiter"

    waiting = asyncio.create_task(ledger.wait(waiter))
    result = {"nested": [1]}
    await ledger.complete(owner, result)
    result["nested"].append(2)
    waited = await waiting
    replay = await _claim(ledger, "call")

    assert waited.result == {"nested": [1]}
    assert replay.kind == "completed"
    assert replay.resolution is not None
    assert replay.resolution.result == {"nested": [1]}
    assert isinstance(waited.result, dict)
    waited.result["nested"].append(3)
    assert replay.resolution.result == {"nested": [1]}


@pytest.mark.asyncio
async def test_waiter_cancellation_does_not_cancel_owner_future() -> None:
    ledger = InMemoryToolIdempotencyLedger()
    owner = await _claim(ledger, "call")
    waiter = await _claim(ledger, "call")
    task = asyncio.create_task(ledger.wait(waiter))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await ledger.complete(owner, {"ok": True})
    replay = await _claim(ledger, "call")
    assert replay.kind == "completed"


@pytest.mark.asyncio
async def test_claim_is_transport_data_and_wait_observes_prior_resolution() -> None:
    ledger = InMemoryToolIdempotencyLedger()
    owner = await _claim(ledger, "call")
    waiter = await _claim(ledger, "call")

    assert set(ToolIdempotencyClaim.__annotations__) == {
        "kind",
        "session_id",
        "tool_call_id",
        "claim_token",
        "resolution",
    }
    assert all(
        not isinstance(getattr(waiter, field.name), (asyncio.Future, asyncio.Event))
        for field in fields(waiter)
    )

    failure = ToolIdempotencyFailure(
        error="Tool execution cancelled",
        error_code="TOOL_CANCELLED",
        retryable=True,
        outcome="not_started",
    )
    await ledger.retryable_failure(owner, failure)
    resolution = await ledger.wait(waiter)
    assert resolution.failure == failure

    replacement = await _claim(ledger, "call")
    assert replacement.kind == "owner"
    with pytest.raises(RuntimeError, match="no longer running"):
        await ledger.complete(owner, {"stale": True})


@pytest.mark.asyncio
async def test_ledger_ttl_is_non_sliding_and_lru_access_is_sliding() -> None:
    now = [0.0]
    ledger = InMemoryToolIdempotencyLedger(
        max_entries=2,
        completed_ttl_seconds=10,
        clock=lambda: now[0],
    )
    first = await _claim(ledger, "first")
    second = await _claim(ledger, "second")
    await ledger.complete(first, 1)
    await ledger.complete(second, 2)

    now[0] = 5
    assert (await _claim(ledger, "first")).kind == "completed"
    third = await _claim(ledger, "third")
    assert third.kind == "owner"
    assert (await _claim(ledger, "second")).kind == "owner"

    ttl = InMemoryToolIdempotencyLedger(
        completed_ttl_seconds=10,
        clock=lambda: now[0],
    )
    now[0] = 0
    owner = await _claim(ttl, "ttl")
    await ttl.complete(owner, 1)
    now[0] = 9
    assert (await _claim(ttl, "ttl")).kind == "completed"
    now[0] = 11
    assert (await _claim(ttl, "ttl")).kind == "owner"


@pytest.mark.asyncio
async def test_running_and_unknown_entries_are_never_evicted() -> None:
    ledger = InMemoryToolIdempotencyLedger(max_entries=1)
    running = await _claim(ledger, "running")
    with pytest.raises(IdempotencyCapacityExceeded):
        await _claim(ledger, "other")

    failure = ToolIdempotencyFailure(
        error="Tool execution timed out",
        error_code="TOOL_TIMEOUT",
        retryable=False,
        outcome="unknown",
    )
    await ledger.unknown_outcome(running, failure)
    with pytest.raises(IdempotencyCapacityExceeded):
        await _claim(ledger, "other")
    replay = await _claim(ledger, "running")
    assert replay.kind == "unknown"
    assert replay.resolution is not None
    assert replay.resolution.failure == failure


@pytest.mark.asyncio
async def test_capacity_failure_happens_before_started_or_handler() -> None:
    ledger = InMemoryToolIdempotencyLedger(max_entries=1)
    await _claim(ledger, "occupied")
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    started = False
    executed = False

    async def emit_started() -> None:
        nonlocal started
        started = True

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    outcome = await controller.execute(_invocation("new"), spec, executor, emit_started)
    assert outcome.failure is not None
    assert outcome.failure.error_code == "IDEMPOTENCY_CAPACITY_EXCEEDED"
    assert outcome.failure.retryable is True
    assert outcome.failure.outcome == "not_started"
    assert started is False
    assert executed is False


@pytest.mark.asyncio
async def test_ledger_conflict_and_session_release_are_exact() -> None:
    ledger = InMemoryToolIdempotencyLedger()
    owner = await _claim(ledger, "call", arguments={"value": 1})
    await ledger.complete(owner, {"ok": True})
    with pytest.raises(IdempotencyConflictError):
        await _claim(ledger, "call", arguments={"value": 2})

    collision = await _claim(ledger, "c", session_id="a:b")
    assert collision.kind == "owner"
    with pytest.raises(IdempotencyConflictError):
        await _claim(ledger, "b:c", session_id="a")

    assert await ledger.release_completed("session") == 1
    assert (await _claim(ledger, "call", arguments={"value": 1})).kind == "owner"


@pytest.mark.asyncio
async def test_same_exact_call_executes_once_and_conflicting_reuse_fails_closed() -> (
    None
):
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=4, timeout_seconds=1)
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    executions = 0

    async def executor(invocation: ToolInvocation) -> dict[str, list[int]]:
        nonlocal executions
        executions += 1
        entered.set()
        await release.wait()
        return {"value": [int(invocation.arguments.get("value", 1))]}

    first = asyncio.create_task(
        controller.execute(
            _invocation("same", arguments={"value": 1}),
            spec,
            executor,
            _noop_started,
        )
    )
    await entered.wait()
    second = asyncio.create_task(
        controller.execute(
            _invocation("same", arguments={"value": 1}),
            spec,
            executor,
            _noop_started,
        )
    )
    release.set()
    one, two = await asyncio.gather(first, second)
    assert executions == 1
    assert one.result == two.result == {"value": [1]}
    assert one.result is not two.result

    conflict = await controller.execute(
        _invocation("same", arguments={"value": 2}),
        spec,
        executor,
        _noop_started,
    )
    assert conflict.failure is not None
    assert conflict.failure.error_code == "IDEMPOTENCY_CONFLICT"
    assert executions == 1


@pytest.mark.asyncio
async def test_same_call_id_in_different_sessions_tracks_both_active_tasks() -> None:
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=2, timeout_seconds=0.02)
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="write",
        parallel_safe=True,
    )
    release = asyncio.Event()
    entered = 0

    async def handler(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal entered
        entered += 1
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"ok": True}

    one, two = await asyncio.gather(
        controller.execute(
            _invocation("same", session_id="one"),
            spec,
            handler,
            _noop_started,
        ),
        controller.execute(
            _invocation("same", session_id="two"),
            spec,
            handler,
            _noop_started,
        ),
    )
    assert one.failure is not None and one.failure.outcome == "unknown"
    assert two.failure is not None and two.failure.outcome == "unknown"
    assert entered == 2
    assert await controller.drain_tools(0) == ["same", "same"]
    release.set()
    assert await controller.drain_tools(1) == []


def _deeply_nested_result(depth: int = 2_000) -> object:
    value: object = None
    for _ in range(depth):
        value = {"nested": value}
    return value


def _hostile_container_result(
    kind: Literal["dict", "list"], calls: list[str]
) -> object:
    def hostile(name: str) -> Never:
        calls.append(name)
        raise AssertionError(f"hostile container hook called: {name}")

    if kind == "dict":

        class HostileDict(dict[str, object]):
            def __iter__(self) -> Iterator[str]:
                hostile("__iter__")

            def __getattribute__(self, name: str) -> Any:
                hostile(f"__getattribute__:{name}")

        return HostileDict({"safe": True})

    class HostileList(list[object]):
        def __iter__(self) -> Iterator[object]:
            hostile("__iter__")

        def __getattribute__(self, name: str) -> Any:
            hostile(f"__getattribute__:{name}")

    return HostileList([True])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad", "internal_code"),
    [
        (object(), "INVALID_DURABLE_VALUE"),
        ({"nested": object()}, "INVALID_DURABLE_VALUE"),
        (float("nan"), "INVALID_DURABLE_VALUE"),
        (2**53, "INVALID_DURABLE_VALUE"),
        pytest.param(
            _deeply_nested_result(),
            "INVALID_DURABLE_VALUE",
            id="deeply-nested",
        ),
        ({"value": "😀" * 16_385}, "EVENT_PAYLOAD_TOO_LARGE"),
    ],
)
async def test_invalid_tool_result_becomes_public_failure_and_internal_tombstone(
    bad: object,
    internal_code: str,
) -> None:
    ledger = InMemoryToolIdempotencyLedger()
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    executions = 0

    async def executor(_invocation: ToolInvocation) -> object:
        nonlocal executions
        executions += 1
        return bad

    outcome = await controller.execute(
        _invocation("invalid-result"), spec, executor, _noop_started
    )
    assert outcome.failure is not None
    assert outcome.failure.error == "Invalid tool result"
    assert outcome.failure.error_code == "INVALID_TOOL_RESULT"
    assert outcome.failure.retryable is False
    assert outcome.failure.outcome == "unknown"
    assert executions == 1

    tombstone = await _claim(ledger, "invalid-result")
    assert tombstone.kind == "unknown"
    assert tombstone.resolution is not None
    assert tombstone.resolution.failure is not None
    assert tombstone.resolution.failure.error_code == internal_code
    assert tombstone.resolution.failure.subject == "tool_result"

    replay = await controller.execute(
        _invocation("invalid-result"), spec, executor, _noop_started
    )
    assert replay.failure is not None
    assert replay.failure.error_code == "INVALID_TOOL_RESULT"
    assert replay.failure.retryable is False
    assert replay.failure.outcome == "unknown"
    assert executions == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dict", "list"])
async def test_hostile_container_result_is_tombstoned_without_calling_hooks(
    kind: Literal["dict", "list"],
) -> None:
    class RecordingLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.completed_ids: list[str] = []
            self.unknown_ids: list[str] = []

        async def complete(self, claim: ToolIdempotencyClaim, result: Any) -> None:
            self.completed_ids.append(claim.tool_call_id)
            await super().complete(claim, result)

        async def unknown_outcome(
            self,
            claim: ToolIdempotencyClaim,
            failure: ToolIdempotencyFailure,
        ) -> None:
            self.unknown_ids.append(claim.tool_call_id)
            await super().unknown_outcome(claim, failure)

    calls: list[str] = []
    hostile = _hostile_container_result(kind, calls)
    ledger = RecordingLedger()
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    executions = 0

    async def executor(_invocation: ToolInvocation) -> object:
        nonlocal executions
        executions += 1
        return hostile

    first = await controller.execute(
        _invocation("hostile-result"), spec, executor, _noop_started
    )
    assert first.failure is not None
    assert first.failure.error == "Invalid tool result"
    assert first.failure.error_code == "INVALID_TOOL_RESULT"
    assert first.failure.retryable is False
    assert first.failure.outcome == "unknown"
    assert calls == []
    assert executions == 1
    assert ledger.completed_ids == []
    assert ledger.unknown_ids == ["hostile-result"]

    tombstone = await _claim(ledger, "hostile-result")
    assert tombstone.kind == "unknown"
    assert tombstone.resolution is not None
    assert tombstone.resolution.failure is not None
    assert tombstone.resolution.failure.error_code == "INVALID_DURABLE_VALUE"
    assert tombstone.resolution.failure.subject == "tool_result"

    replay = await controller.execute(
        _invocation("hostile-result"), spec, executor, _noop_started
    )
    assert replay.failure is not None
    assert replay.failure.error == "Invalid tool result"
    assert replay.failure.error_code == "INVALID_TOOL_RESULT"
    assert replay.failure.retryable is False
    assert replay.failure.outcome == "unknown"
    assert calls == []
    assert executions == 1
    assert ledger.completed_ids == []
    assert ledger.unknown_ids == ["hostile-result"]

    async def healthy_executor(
        _invocation: ToolInvocation,
    ) -> dict[str, bool]:
        return {"ok": True}

    healthy = await controller.execute(
        _invocation("healthy-result"), spec, healthy_executor, _noop_started
    )
    assert healthy.failure is None
    assert healthy.result == {"ok": True}
    assert ledger.completed_ids == ["healthy-result"]
    assert ledger.unknown_ids == ["hostile-result"]
    assert calls == []


@pytest.mark.asyncio
async def test_ledger_completion_io_failure_remains_distinct_from_invalid_result() -> (
    None
):
    class BrokenCompleteLedger(InMemoryToolIdempotencyLedger):
        async def complete(self, claim: Any, result: Any) -> None:
            del claim, result
            raise RuntimeError("ledger unavailable")

    ledger = BrokenCompleteLedger()
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    executions = 0

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal executions
        executions += 1
        return {"ok": True}

    outcome = await controller.execute(
        _invocation("ledger-failure"), spec, executor, _noop_started
    )
    assert outcome.failure is not None
    assert outcome.failure.error_code == "TOOL_EXECUTION_FAILED"
    assert outcome.failure.retryable is False
    assert outcome.failure.outcome == "unknown"

    tombstone = await _claim(ledger, "ledger-failure")
    assert tombstone.kind == "unknown"
    assert tombstone.resolution is not None
    assert tombstone.resolution.failure is not None
    assert tombstone.resolution.failure.error_code == "TOOL_EXECUTION_FAILED"
    assert tombstone.resolution.failure.subject is None

    replay = await controller.execute(
        _invocation("ledger-failure"), spec, executor, _noop_started
    )
    assert replay.failure is not None
    assert replay.failure.error_code == "TOOL_EXECUTION_FAILED"
    assert executions == 1


@pytest.mark.asyncio
async def test_invalid_tool_result_does_not_poison_runtime_or_projection() -> None:
    executions = 0

    class PoisonIntegration:
        def register(self, registry: Any) -> None:
            spec = ToolSpec(
                name="poison",
                description="Return a hostile value",
                parameters={"type": "object", "properties": {}},
                risk="write",
            )

            async def poison(_context: Any, _arguments: Any) -> object:
                nonlocal executions
                executions += 1
                return {"bad": object()}

            registry.register(spec)(poison)

    store = InMemoryEventStore()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .integration(PoisonIntegration())
        .build(store=store)
    )
    context = TurnContext(principal_id="principal")

    first = await runtime.turn(
        "call it",
        session_id="invalid-tool-result",
        context=context,
    )
    failures = [
        event for event in first.events if event.type == EventType.TOOL_CALL_FAILED
    ]
    assert len(failures) == 1
    assert failures[0].error == "Invalid tool result"
    assert failures[0].error_code == "INVALID_TOOL_RESULT"
    assert failures[0].retryable is False
    assert failures[0].outcome == "unknown"
    assert not any(
        event.type == EventType.TOOL_CALL_COMPLETED for event in first.events
    )
    assert first.events[-1].type == EventType.AGENT_MESSAGE_COMPLETED
    assert executions == 1

    projector = SessionProjector("invalid-tool-result")
    await projector.sync(store)
    replay_session(await store.get_events("invalid-tool-result"))

    second = await runtime.turn(
        "continue",
        session_id="invalid-tool-result",
        context=context,
    )
    assert second.text == "mock"
    assert second.events[-1].type == EventType.AGENT_MESSAGE_COMPLETED
    assert executions == 1
    replay_session(await store.get_events("invalid-tool-result"))


@pytest.mark.asyncio
async def test_only_typed_known_failure_is_removed_for_retry() -> None:
    controller = ToolExecutionController()
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    executions = 0

    async def executor(_invocation: ToolInvocation) -> None:
        nonlocal executions
        executions += 1
        raise ToolExecutionError()

    first = await controller.execute(
        _invocation("known-failure"), spec, executor, _noop_started
    )
    second = await controller.execute(
        _invocation("known-failure"), spec, executor, _noop_started
    )
    for outcome in (first, second):
        assert outcome.failure is not None
        assert outcome.failure.outcome == "failed"
        assert outcome.failure.retryable is True
    assert executions == 2


@pytest.mark.asyncio
async def test_parent_task_cancellation_after_settlement_tombstones_claim() -> None:
    class PausingLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.complete_started = asyncio.Event()

        async def complete(self, claim, result) -> None:
            self.complete_started.set()
            await asyncio.Event().wait()

    ledger = PausingLedger()
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        return {"ok": True}

    running = asyncio.create_task(
        controller.execute(
            _invocation("cancel-after-settle"),
            spec,
            executor,
            _noop_started,
        )
    )
    await ledger.complete_started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    replay = await ledger.claim(
        session_id="session",
        tool_call_id="cancel-after-settle",
        tool_name="tool",
        tool_args={},
    )
    assert replay.kind == "unknown"


@pytest.mark.asyncio
async def test_started_append_failure_rolls_back_without_invoking_handler() -> None:
    calls = 0
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="read")

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    planner = ToolPlanner(executor, specs={"tool": spec})

    async def broken(event: Any) -> None:
        if event.type == EventType.TOOL_CALL_STARTED:
            raise RuntimeError("journal unavailable")

    with pytest.raises(ExceptionGroup):
        await planner.execute_batch(
            "session",
            [{"id": "call", "name": "tool", "arguments": {}}],
            broken,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
        )
    assert calls == 0
    assert await planner.controller.drain_tools(0) == []

    events: list[Any] = []

    async def emit(event: Any) -> None:
        events.append(event)

    await planner.execute_batch(
        "session",
        [{"id": "call", "name": "tool", "arguments": {}}],
        emit,
        turn_id="turn-2",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_completed_append_failure_never_emits_fallback_failed() -> None:
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="read")
    planner = ToolPlanner(
        lambda _invocation: asyncio.sleep(0, result={"ok": True}),
        specs={"tool": spec},
    )
    attempted: list[EventType] = []

    async def emit(event: Any) -> None:
        attempted.append(event.type)
        if event.type == EventType.TOOL_CALL_COMPLETED:
            raise RuntimeError("ambiguous append")

    with pytest.raises(ExceptionGroup):
        await planner.execute_batch(
            "session",
            [{"id": "call", "name": "tool", "arguments": {}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
        )

    assert attempted == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
    ]
    assert EventType.TOOL_CALL_FAILED not in attempted


@pytest.mark.asyncio
async def test_explicit_runtime_and_planner_share_controller_for_drain() -> None:
    controller = ToolExecutionController(ToolExecutionLimits(timeout_seconds=0.02))
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    planner = ToolPlanner(
        lambda _invocation: asyncio.sleep(0, result={}),
        specs={"tool": spec},
        controller=controller,
    )
    runtime = AgentRuntime(
        bus=None,
        store=InMemoryEventStore(),
        provider=MockProvider(),
        planner=planner,
        tools=[spec],
        tool_execution_controller=controller,
    )
    assert runtime.tool_execution_controller is planner.controller is controller
    assert await runtime.drain_tools(0) == []

    release = asyncio.Event()

    async def noncooperative(_invocation: ToolInvocation) -> dict[str, bool]:
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"ok": True}

    outcome = await controller.execute(
        _invocation("stuck"), spec, noncooperative, _noop_started
    )
    assert outcome.failure is not None and outcome.failure.outcome == "unknown"
    assert await runtime.drain_tools(0) == ["stuck"]
    release.set()
    assert await runtime.drain_tools(1) == []

    with pytest.raises(ValueError, match="share the same"):
        AgentRuntime(
            bus=None,
            store=InMemoryEventStore(),
            provider=MockProvider(),
            planner=planner,
            tools=[spec],
            tool_execution_controller=ToolExecutionController(),
        )


def test_builder_injects_limits_and_ledger_into_runtime_controller() -> None:
    limits = ToolExecutionLimits(max_parallel=2, timeout_seconds=3)
    ledger = InMemoryToolIdempotencyLedger()
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .tool_execution_limits(limits)
        .tool_idempotency_ledger(ledger)
        .build()
    )

    assert runtime.tool_execution_controller is runtime.planner.controller
    assert runtime.tool_execution_controller.limits is limits
    assert runtime.tool_execution_controller.ledger is ledger


def test_vendor_clients_disable_opaque_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    from kaji.runtime.providers import anthropic as anthropic_module
    from kaji.runtime.providers import openai as openai_module

    captured: dict[str, dict[str, Any]] = {}

    def openai_client(**kwargs: Any) -> object:
        captured["openai"] = kwargs
        return object()

    def anthropic_client(**kwargs: Any) -> object:
        captured["anthropic"] = kwargs
        return object()

    monkeypatch.setattr(
        openai_module,
        "import_module",
        lambda _name: SimpleNamespace(AsyncOpenAI=openai_client),
    )
    monkeypatch.setattr(
        anthropic_module,
        "import_module",
        lambda _name: SimpleNamespace(AsyncAnthropic=anthropic_client),
    )
    assert openai_module.OpenAIProvider(api_key="key").client is not None
    assert anthropic_module.AnthropicProvider(api_key="key").client is not None
    assert captured["openai"]["max_retries"] == 0
    assert captured["anthropic"]["max_retries"] == 0


@pytest.mark.asyncio
async def test_gate_acquisition_cancellation_race_releases_safe_claim() -> None:
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1)
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    original = controller._acquire_gate
    execution_task: asyncio.Task[Any]
    fired = False

    async def racing_gate(parallel_safe: bool) -> None:
        nonlocal fired
        await original(parallel_safe)
        if not fired:
            fired = True
            execution_task.cancel()

    controller._acquire_gate = racing_gate  # ty: ignore[invalid-assignment]
    execution_task = asyncio.create_task(
        controller.execute(
            _invocation("gate-race"),
            spec,
            lambda _invocation: asyncio.sleep(0, result={"ok": True}),
            _noop_started,
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await execution_task
    assert controller._safe_claims == 0

    controller._acquire_gate = original  # ty: ignore[invalid-assignment]
    retry = await controller.execute(
        _invocation("gate-race"),
        spec,
        lambda _invocation: asyncio.sleep(0, result={"ok": True}),
        _noop_started,
    )
    assert retry.succeeded


@pytest.mark.asyncio
async def test_semaphore_acquisition_cancellation_race_releases_permit() -> None:
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1)
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    original = controller._semaphore

    class RacingSemaphore:
        def __init__(self) -> None:
            self.target: asyncio.Task[Any] | None = None
            self.fired = False

        async def acquire(self) -> bool:
            acquired = await original.acquire()
            if not self.fired:
                self.fired = True
                assert self.target is not None
                self.target.cancel()
            return acquired

        def release(self) -> None:
            original.release()

    racing = RacingSemaphore()
    controller._semaphore = racing  # ty: ignore[invalid-assignment]
    execution_task = asyncio.create_task(
        controller.execute(
            _invocation("permit-race"),
            spec,
            lambda _invocation: asyncio.sleep(0, result={"ok": True}),
            _noop_started,
        )
    )
    racing.target = execution_task
    with pytest.raises(asyncio.CancelledError):
        await execution_task

    controller._semaphore = original
    retry = await controller.execute(
        _invocation("permit-race"),
        spec,
        lambda _invocation: asyncio.sleep(0, result={"ok": True}),
        _noop_started,
    )
    assert retry.succeeded


@pytest.mark.asyncio
async def test_started_append_deadline_and_cancellation_never_run_handler() -> None:
    now = [0.0]
    controller = ToolExecutionController(
        ToolExecutionLimits(timeout_seconds=10),
        clock=lambda: now[0],
    )
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    executed = False

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    async def expires_after_append() -> None:
        now[0] = 11

    expired = await controller.execute(
        _invocation("slow-start"), spec, executor, expires_after_append
    )
    assert expired.failure is not None
    assert expired.failure.error_code == "TOOL_TIMEOUT"
    assert expired.failure.outcome == "not_started"
    assert executed is False

    timeout_entered = asyncio.Event()

    async def timeout_append() -> None:
        timeout_entered.set()
        await asyncio.Event().wait()

    timed = asyncio.create_task(
        ToolExecutionController(ToolExecutionLimits(timeout_seconds=0.01)).execute(
            _invocation("timeout-start"),
            spec,
            executor,
            timeout_append,
        )
    )
    await timeout_entered.wait()
    timed_out = await timed
    assert timed_out.failure is not None
    assert timed_out.failure.error_code == "TOOL_TIMEOUT"
    assert timed_out.failure.outcome == "not_started"
    assert executed is False

    token = CancellationToken()
    entered = asyncio.Event()

    async def slow_append() -> None:
        entered.set()
        await asyncio.Event().wait()

    pending = asyncio.create_task(
        ToolExecutionController(ToolExecutionLimits(timeout_seconds=1)).execute(
            _invocation("cancel-start", token=token),
            spec,
            executor,
            slow_append,
        )
    )
    await entered.wait()
    token.cancel()
    cancelled = await pending
    assert cancelled.failure is not None
    assert cancelled.failure.error_code == "TOOL_CANCELLED"
    assert cancelled.failure.outcome == "not_started"
    assert executed is False


@pytest.mark.asyncio
async def test_slow_cancel_suppressing_claim_is_cleaned_after_timeout() -> None:
    class SlowClaimLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.release_claim = asyncio.Event()

        async def claim(self, **kwargs: Any):
            try:
                await self.release_claim.wait()
            except asyncio.CancelledError:
                await self.release_claim.wait()
            return await super().claim(**kwargs)

    ledger = SlowClaimLedger()
    controller = ToolExecutionController(
        ToolExecutionLimits(timeout_seconds=0.01),
        ledger=ledger,
    )
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    outcome = await asyncio.wait_for(
        controller.execute(
            _invocation("late-claim"),
            spec,
            lambda _invocation: asyncio.sleep(0, result={}),
            _noop_started,
        ),
        timeout=0.2,
    )
    assert outcome.failure is not None
    assert outcome.failure.error_code == "TOOL_TIMEOUT"
    assert outcome.failure.outcome == "not_started"

    ledger.release_claim.set()
    await _wait_until(lambda: not controller._pending_setup)
    fresh = await _claim(ledger, "late-claim")
    assert fresh.kind == "owner"


@pytest.mark.asyncio
async def test_stuck_claim_setup_is_bounded_backpressured_and_drained() -> None:
    class StuckClaimLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.sessions: list[str] = []
            self.active = 0
            self.peak = 0

        async def claim(self, **kwargs: Any):
            self.sessions.append(kwargs["session_id"])
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 4:
                self.entered.set()
            try:
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    await self.release.wait()
                return await super().claim(**kwargs)
            finally:
                self.active -= 1

    ledger = StuckClaimLedger()
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=4, timeout_seconds=0.02),
        ledger=ledger,
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )

    first_four = [
        asyncio.create_task(
            controller.execute(
                _invocation("same", session_id=f"session-{index}"),
                spec,
                lambda _invocation: asyncio.sleep(0, result={}),
                _noop_started,
            )
        )
        for index in range(4)
    ]
    await ledger.entered.wait()
    outcomes = await asyncio.gather(*first_four)
    assert all(
        outcome.failure is not None
        and outcome.failure.error_code == "TOOL_TIMEOUT"
        and outcome.failure.outcome == "not_started"
        for outcome in outcomes
    )
    assert ledger.peak == 4
    assert await controller.drain_tools(0) == ["same"] * 4

    fifth = await controller.execute(
        _invocation("fifth", session_id="session-5"),
        spec,
        lambda _invocation: asyncio.sleep(0, result={}),
        _noop_started,
    )
    assert fifth.failure is not None
    assert fifth.failure.error_code == "TOOL_TIMEOUT"
    assert fifth.failure.outcome == "not_started"
    assert "session-5" not in ledger.sessions
    assert await controller.drain_tools(0) == ["same"] * 4

    ledger.release.set()
    assert await controller.drain_tools(1) == []
    assert ledger.active == 0


@pytest.mark.asyncio
async def test_late_mark_started_is_unknown_drained_and_never_runs_handler() -> None:
    class StuckMarkLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def mark_started(self, claim) -> None:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()
            await super().mark_started(claim)

    ledger = StuckMarkLedger()
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=0.02),
        ledger=ledger,
    )
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    started = False
    executed = False

    async def emit_started() -> None:
        nonlocal started
        started = True

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    running = asyncio.create_task(
        controller.execute(
            _invocation("late-mark"),
            spec,
            executor,
            emit_started,
        )
    )
    await ledger.entered.wait()
    outcome = await asyncio.wait_for(running, timeout=0.2)
    assert outcome.failure is not None
    assert outcome.failure.error_code == "TOOL_TIMEOUT"
    assert outcome.failure.retryable is False
    assert outcome.failure.outcome == "unknown"
    assert started is True
    assert executed is False
    assert await controller.drain_tools(0) == ["late-mark"]

    ledger.release.set()
    assert await controller.drain_tools(1) == []
    replay = await _claim(ledger, "late-mark")
    assert replay.kind == "unknown"

    cancelled_ledger = StuckMarkLedger()
    cancelled_controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1),
        ledger=cancelled_ledger,
    )
    cancelled = asyncio.create_task(
        cancelled_controller.execute(
            _invocation("cancelled-mark"),
            spec,
            executor,
            emit_started,
        )
    )
    await cancelled_ledger.entered.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cancelled, timeout=0.2)
    assert executed is False
    assert await cancelled_controller.drain_tools(0) == ["cancelled-mark"]

    cancelled_ledger.release.set()
    assert await cancelled_controller.drain_tools(1) == []
    cancelled_replay = await _claim(cancelled_ledger, "cancelled-mark")
    assert cancelled_replay.kind == "unknown"


@pytest.mark.asyncio
async def test_duplicate_waiter_certainty_tracks_owner_start_boundary() -> None:
    class ObservedLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.duplicate_claimed = asyncio.Event()

        async def claim(self, **kwargs: Any):
            claim = await super().claim(**kwargs)
            if kwargs["tool_call_id"] == "duplicate" and claim.kind == "owner":
                self.duplicate_claimed.set()
            return claim

    ledger = ObservedLedger()
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1),
        ledger=ledger,
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="write",
        parallel_safe=True,
    )
    blocker_started = asyncio.Event()
    duplicate_started = asyncio.Event()
    release_blocker = asyncio.Event()
    release_duplicate = asyncio.Event()

    async def executor(invocation: ToolInvocation) -> dict[str, bool]:
        if invocation.context.tool_call_id == "blocker":
            blocker_started.set()
            await release_blocker.wait()
        else:
            duplicate_started.set()
            await release_duplicate.wait()
        return {"ok": True}

    blocker = asyncio.create_task(
        controller.execute(_invocation("blocker"), spec, executor, _noop_started)
    )
    await blocker_started.wait()
    owner = asyncio.create_task(
        controller.execute(_invocation("duplicate"), spec, executor, _noop_started)
    )
    await ledger.duplicate_claimed.wait()

    queued_token = CancellationToken()
    queued_waiter = asyncio.create_task(
        controller.execute(
            _invocation("duplicate", token=queued_token),
            spec,
            executor,
            _noop_started,
        )
    )
    await asyncio.sleep(0)
    queued_token.cancel()
    queued = await queued_waiter
    assert queued.failure is not None
    assert queued.failure.outcome == "not_started"
    assert queued.failure.retryable is True

    release_blocker.set()
    await duplicate_started.wait()
    started_token = CancellationToken()
    started_waiter = asyncio.create_task(
        controller.execute(
            _invocation("duplicate", token=started_token),
            spec,
            executor,
            _noop_started,
        )
    )
    await asyncio.sleep(0)
    started_token.cancel()
    started = await started_waiter
    assert started.failure is not None
    assert started.failure.outcome == "unknown"
    assert started.failure.retryable is False

    release_duplicate.set()
    assert (await owner).succeeded
    assert (await blocker).succeeded


@pytest.mark.asyncio
async def test_stuck_started_lookup_is_bounded_conservative_and_drained() -> None:
    class StuckLookupLedger(InMemoryToolIdempotencyLedger):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def is_started(self, claim) -> bool:
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()
            return await super().is_started(claim)

    ledger = StuckLookupLedger()
    owner = await _claim(ledger, "lookup")
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1),
        ledger=ledger,
    )
    token = CancellationToken()
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    waiting = asyncio.create_task(
        controller.execute(
            _invocation("lookup", token=token),
            spec,
            lambda _invocation: asyncio.sleep(0, result={}),
            _noop_started,
        )
    )
    await asyncio.sleep(0)
    token.cancel()
    await ledger.entered.wait()

    outcome = await asyncio.wait_for(waiting, timeout=0.5)
    assert outcome.failure is not None
    assert outcome.failure.error_code == "TOOL_CANCELLED"
    assert outcome.failure.retryable is False
    assert outcome.failure.outcome == "unknown"
    assert await controller.drain_tools(0) == ["lookup"]

    ledger.release.set()
    assert await controller.drain_tools(1) == []
    await ledger.retryable_failure(
        owner,
        ToolIdempotencyFailure(
            error="Tool execution cancelled",
            error_code="TOOL_CANCELLED",
            retryable=True,
            outcome="not_started",
        ),
    )


@pytest.mark.asyncio
async def test_non_json_argument_is_rejected_before_requested() -> None:
    planner = ToolPlanner(
        lambda _invocation: asyncio.sleep(0, result={}),
        specs={
            "tool": ToolSpec(
                name="tool", description="tool", parameters={}, risk="read"
            )
        },
    )
    events: list[Any] = []

    async def emit(event: Any) -> None:
        events.append(event)

    with pytest.raises(ToolArgumentValidationError, match="only JSON values"):
        await planner.execute_batch(
            "session",
            [{"id": "bad-json", "name": "tool", "arguments": {"x": object()}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
        )
    assert events == []


def test_falsy_ledger_is_preserved_and_ttl_must_be_finite() -> None:
    class FalsyLedger(InMemoryToolIdempotencyLedger):
        def __bool__(self) -> bool:
            return False

    ledger = FalsyLedger()
    assert ToolExecutionController(ledger=ledger).ledger is ledger
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="completed_ttl_seconds"):
            InMemoryToolIdempotencyLedger(completed_ttl_seconds=value)


@pytest.mark.asyncio
async def test_ledger_claim_operational_error_is_sanitized_and_terminal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "ledger-storage-secret"

    class BrokenClaimLedger(InMemoryToolIdempotencyLedger):
        async def claim(self, **_kwargs: Any):
            raise RuntimeError(secret)

    ledger = BrokenClaimLedger()
    controller = ToolExecutionController(ledger=ledger)
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    started = False
    executed = False

    async def emit_started() -> None:
        nonlocal started
        started = True

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    controller_outcome = await controller.execute(
        _invocation("controller-claim-fault"),
        spec,
        executor,
        emit_started,
    )
    assert controller_outcome.failure is not None
    assert controller_outcome.failure.error == "Tool execution failed"
    assert controller_outcome.failure.error_code == "TOOL_EXECUTION_FAILED"
    assert controller_outcome.failure.retryable is True
    assert controller_outcome.failure.outcome == "not_started"
    assert isinstance(controller_outcome.failure.cause, RuntimeError)
    assert secret in str(controller_outcome.failure.cause)
    assert started is False
    assert executed is False

    planner = ToolPlanner(
        executor,
        specs={"tool": spec},
        idempotency_ledger=ledger,
    )
    events: list[Any] = []

    async def emit(event: Any) -> None:
        events.append(event)

    results = await planner.execute_batch(
        "session",
        [{"id": "planner-claim-fault", "name": "tool", "arguments": {}}],
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )
    assert results == [
        {
            "id": "planner-claim-fault",
            "name": "tool",
            "error": "Tool execution failed",
            "error_code": "TOOL_EXECUTION_FAILED",
            "retryable": True,
            "outcome": "not_started",
        }
    ]
    assert [event.type for event in events] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
    ]
    public_text = " ".join(
        [repr(results), *(event.model_dump_json() for event in events)]
    )
    assert secret not in public_text
    assert secret not in caplog.text
    assert started is False
    assert executed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mid_stream",
    [
        pytest.param(False, id="before-output"),
        pytest.param(True, id="mid-stream"),
    ],
)
async def test_provider_fault_is_single_terminal_replayable_and_releases_runtime(
    mid_stream: bool,
) -> None:
    secret = "provider-private-secret"

    class FailThenRecoverProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
            return GenerateResponse(text="")

        async def generate_stream(
            self, *_args: Any, **_kwargs: Any
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            self.calls += 1
            if self.calls == 1:
                if mid_stream:
                    yield ModelResponseChunk(delta="partial")
                raise RuntimeError(secret)
            yield ModelResponseChunk(delta="recovered")

    provider = FailThenRecoverProvider()
    coordinator = InMemoryTurnCoordinator()
    store = InMemoryEventStore()
    runtime = (
        AgentBuilder().provider(provider).coordinator(coordinator).build(store=store)
    )

    with pytest.raises(RuntimeError, match=secret):
        await runtime.turn("first", session_id="provider-fault")

    failed_history = await store.get_events("provider-fault")
    failure_events = [
        event for event in failed_history if event.type == EventType.AGENT_TURN_FAILED
    ]
    assert len(failure_events) == 1
    failed_turn_id = failure_events[0].turn_id
    assert secret not in failure_events[0].model_dump_json()
    assert not any(
        event.type == EventType.AGENT_MESSAGE_COMPLETED
        and event.turn_id == failed_turn_id
        for event in failed_history
    )
    deltas = [
        event
        for event in failed_history
        if event.type == EventType.AGENT_MESSAGE_DELTA
        and event.turn_id == failed_turn_id
    ]
    assert [event.delta for event in deltas] == (["partial"] if mid_stream else [])
    replay_session(failed_history)
    assert coordinator.entry_count == coordinator.waiter_count == 0

    recovered = await runtime.turn("second", session_id="provider-fault")
    assert recovered.text == "recovered"
    replay_session(await store.get_events("provider-fault"))
    assert coordinator.entry_count == coordinator.waiter_count == 0
