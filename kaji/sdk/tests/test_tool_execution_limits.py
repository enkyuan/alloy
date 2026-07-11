from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import pytest

from kaji.infra.events.types import EventType
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import (
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.integrations.base import Integration, tool
from kaji.runtime.integrations.functional import function_tool
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec


def _invocation(
    call_id: str,
    *,
    session_id: str = "session",
    token: CancellationToken | None = None,
    arguments: dict[str, Any] | None = None,
) -> ToolInvocation:
    resolved_token = token or CancellationToken()
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
            cancellation_token=resolved_token,
            deadline_monotonic=None,
            db=None,
            metadata={},
        ),
    )


async def _noop_started() -> None:
    return None


@pytest.mark.asyncio
async def test_parallel_safe_batch_is_bounded_and_terminal_order_is_stable() -> None:
    active = 0
    peak = 0

    async def executor(invocation: ToolInvocation) -> dict[str, str]:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        index = int(invocation.context.tool_call_id.removeprefix("call-"))
        await asyncio.sleep((20 - index) / 10_000)
        active -= 1
        return {"id": invocation.context.tool_call_id}

    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={"type": "object"},
        risk="read",
        parallel_safe=True,
    )
    planner = ToolPlanner(executor, specs={"tool": spec})
    events: list[Any] = []
    calls = [
        {"id": f"call-{index}", "name": "tool", "arguments": {}} for index in range(20)
    ]

    async def emit(event: Any) -> None:
        events.append(event)

    results = await planner.execute_batch(
        "session",
        calls,
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )

    assert peak == 4
    assert [result["id"] for result in results] == [call["id"] for call in calls]
    terminal_ids = [
        event.tool_call_id
        for event in events
        if event.type in (EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED)
    ]
    assert terminal_ids == [call["id"] for call in calls]


@pytest.mark.asyncio
async def test_parallel_safe_batch_uses_a_fixed_number_of_planner_tasks() -> None:
    baseline_task_count = len(asyncio.all_tasks())
    peak_task_count = baseline_task_count

    async def executor(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal peak_task_count
        peak_task_count = max(peak_task_count, len(asyncio.all_tasks()))
        return {"ok": True}

    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    planner = ToolPlanner(
        executor,
        specs={"tool": spec},
        execution_limits=ToolExecutionLimits(max_parallel=1, timeout_seconds=1),
    )

    async def emit(_event: Any) -> None:
        return None

    calls = [
        {"id": f"call-{index}", "name": "tool", "arguments": {}} for index in range(200)
    ]
    results = await planner.execute_batch(
        "session",
        calls,
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )

    assert len(results) == len(calls)
    assert peak_task_count <= baseline_task_count + 8


@pytest.mark.asyncio
async def test_default_tools_are_exclusive_barriers() -> None:
    active: set[str] = set()
    unsafe_overlap = False
    peak = 0

    async def executor(invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal unsafe_overlap, peak
        call_id = invocation.context.tool_call_id
        active.add(call_id)
        peak = max(peak, len(active))
        if call_id.startswith("unsafe") and len(active) != 1:
            unsafe_overlap = True
        if not call_id.startswith("unsafe") and any(
            active_id.startswith("unsafe") for active_id in active
        ):
            unsafe_overlap = True
        await asyncio.sleep(0.005)
        active.remove(call_id)
        return {"ok": True}

    safe = ToolSpec(
        name="safe",
        description="safe",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    unsafe = ToolSpec(
        name="unsafe",
        description="unsafe",
        parameters={},
        risk="write",
    )
    planner = ToolPlanner(executor, specs={"safe": safe, "unsafe": unsafe})

    async def emit(_event: Any) -> None:
        return None

    await planner.execute_batch(
        "session",
        [
            {"id": "safe-1", "name": "safe", "arguments": {}},
            {"id": "safe-2", "name": "safe", "arguments": {}},
            {"id": "unsafe-1", "name": "unsafe", "arguments": {}},
            {"id": "unsafe-2", "name": "unsafe", "arguments": {}},
            {"id": "safe-3", "name": "safe", "arguments": {}},
            {"id": "safe-4", "name": "safe", "arguments": {}},
        ],
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )

    assert peak == 2
    assert unsafe_overlap is False


@pytest.mark.asyncio
async def test_queue_cancellation_and_timeout_never_emit_started() -> None:
    release = asyncio.Event()
    first_started = asyncio.Event()
    starts: list[str] = []
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=1)
    )
    safe = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )

    async def executor(invocation: ToolInvocation) -> dict[str, bool]:
        if invocation.context.tool_call_id == "first":
            first_started.set()
            await release.wait()
        return {"ok": True}

    async def run(call_id: str, token: CancellationToken, spec: ToolSpec = safe):
        async def started() -> None:
            starts.append(call_id)

        return await controller.execute(
            _invocation(call_id, token=token), spec, executor, started
        )

    first = asyncio.create_task(run("first", CancellationToken()))
    await first_started.wait()

    cancelled_token = CancellationToken()
    cancelled = asyncio.create_task(run("cancelled", cancelled_token))
    await asyncio.sleep(0)
    cancelled_token.cancel()
    cancelled_outcome = await cancelled
    assert cancelled_outcome.failure is not None
    assert cancelled_outcome.failure.error_code == "TOOL_CANCELLED"
    assert cancelled_outcome.failure.outcome == "not_started"

    short = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
        timeout_ms=10,
    )
    timeout_outcome = await run("timed-out", CancellationToken(), short)
    assert timeout_outcome.failure is not None
    assert timeout_outcome.failure.error_code == "TOOL_TIMEOUT"
    assert timeout_outcome.failure.outcome == "not_started"
    assert starts == ["first"]

    release.set()
    await first
    assert await controller.drain_tools(0.1) == []


@pytest.mark.asyncio
async def test_noncooperative_timeout_retains_permits_and_blocks_fifth_start() -> None:
    releases = {f"call-{index}": asyncio.Event() for index in range(4)}
    running: set[str] = set()
    starts: list[str] = []
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=4, timeout_seconds=0.02)
    )
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="write",
        parallel_safe=True,
    )

    async def noncooperative(invocation: ToolInvocation) -> dict[str, bool]:
        call_id = invocation.context.tool_call_id
        running.add(call_id)
        try:
            await releases[call_id].wait()
        except asyncio.CancelledError:
            await releases[call_id].wait()
        running.remove(call_id)
        return {"ok": True}

    async def run(call_id: str):
        async def started() -> None:
            starts.append(call_id)

        return await controller.execute(
            _invocation(call_id), spec, noncooperative, started
        )

    outcomes = await asyncio.gather(*(run(call_id) for call_id in releases))
    assert all(
        outcome.failure is not None
        and outcome.failure.error_code == "TOOL_TIMEOUT"
        and outcome.failure.outcome == "unknown"
        for outcome in outcomes
    )
    assert sorted(await controller.drain_tools(0)) == sorted(releases)
    assert len(running) == 4

    fifth = await run("fifth")
    assert fifth.failure is not None
    assert fifth.failure.error_code == "TOOL_TIMEOUT"
    assert fifth.failure.outcome == "not_started"
    assert "fifth" not in starts

    for release in releases.values():
        release.set()
    assert await controller.drain_tools(1) == []


@pytest.mark.asyncio
async def test_running_timeout_signals_the_child_cancellation_token() -> None:
    observed = asyncio.Event()
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, timeout_seconds=0.02)
    )
    spec = ToolSpec(name="tool", description="tool", parameters={}, risk="write")

    async def cooperative(invocation: ToolInvocation) -> dict[str, bool]:
        try:
            await invocation.context.cancellation_token.wait()
        finally:
            if invocation.context.cancellation_token.is_cancelled:
                observed.set()
        return {"ok": True}

    outcome = await controller.execute(
        _invocation("cooperative"), spec, cooperative, _noop_started
    )
    assert outcome.failure is not None
    assert outcome.failure.error_code == "TOOL_TIMEOUT"
    assert outcome.failure.outcome == "unknown"
    await asyncio.wait_for(observed.wait(), timeout=1)
    assert await controller.drain_tools(1) == []


@pytest.mark.asyncio
async def test_timed_out_unsafe_handler_remains_an_exclusive_barrier() -> None:
    release = asyncio.Event()
    unsafe_started = asyncio.Event()
    safe_called = False
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=4, timeout_seconds=0.02)
    )
    unsafe = ToolSpec(name="tool", description="tool", parameters={}, risk="write")
    safe = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )

    async def unsafe_handler(_invocation: ToolInvocation) -> dict[str, bool]:
        unsafe_started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return {"ok": True}

    unsafe_outcome = await controller.execute(
        _invocation("unsafe"), unsafe, unsafe_handler, _noop_started
    )
    assert unsafe_started.is_set()
    assert unsafe_outcome.failure is not None
    assert unsafe_outcome.failure.outcome == "unknown"

    async def safe_handler(_invocation: ToolInvocation) -> dict[str, bool]:
        nonlocal safe_called
        safe_called = True
        return {"ok": True}

    safe_outcome = await controller.execute(
        _invocation("safe"), safe, safe_handler, _noop_started
    )
    assert safe_outcome.failure is not None
    assert safe_outcome.failure.outcome == "not_started"
    assert safe_called is False

    release.set()
    assert await controller.drain_tools(1) == []


@pytest.mark.asyncio
async def test_parent_token_cancels_running_and_queued_siblings_once() -> None:
    token = CancellationToken()
    entered = 0
    spec = ToolSpec(
        name="tool",
        description="tool",
        parameters={},
        risk="read",
        parallel_safe=True,
    )
    planner = ToolPlanner(
        lambda invocation: invocation.context.cancellation_token.wait(),
        specs={"tool": spec},
        execution_limits=ToolExecutionLimits(max_parallel=4, timeout_seconds=1),
    )
    events: list[Any] = []

    async def emit(event: Any) -> None:
        nonlocal entered
        events.append(event)
        if event.type == EventType.TOOL_CALL_STARTED:
            entered += 1
            if entered == 4:
                token.cancel()

    results = await planner.execute_batch(
        "session",
        [
            {"id": f"call-{index}", "name": "tool", "arguments": {}}
            for index in range(8)
        ],
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=token,
    )

    assert all(result["error_code"] == "TOOL_CANCELLED" for result in results)
    terminal_counts = Counter(
        event.tool_call_id
        for event in events
        if event.type in (EventType.TOOL_CALL_COMPLETED, EventType.TOOL_CALL_FAILED)
    )
    assert terminal_counts == Counter({f"call-{index}": 1 for index in range(8)})
    assert await planner.controller.drain_tools(1) == []


def test_tool_execution_fields_validate_snapshot_and_thread_through_integrations() -> (
    None
):
    configured = ToolSpec(
        name="configured",
        description="configured",
        parameters={},
        risk="read",
        parallel_safe=True,
        timeout_ms=125,
    )
    registry = ToolRegistry()

    @registry.register(configured)
    async def configured_handler(_context, _args):
        return {}

    snapshot = registry.list_specs()[0]
    assert snapshot.parallel_safe is True
    assert snapshot.timeout_ms == 125

    with pytest.raises(TypeError, match="parallel_safe"):
        ToolSpec(
            name="bad",
            description="bad",
            parameters={},
            risk="read",
            parallel_safe=1,  # ty: ignore[invalid-argument-type]
        )
    with pytest.raises(TypeError, match="timeout_ms"):
        ToolSpec(
            name="bad", description="bad", parameters={}, risk="read", timeout_ms=True
        )
    with pytest.raises(ValueError, match="timeout_ms"):
        ToolSpec(
            name="bad", description="bad", parameters={}, risk="read", timeout_ms=0
        )

    class Decorated(Integration):
        namespace = "decorated"

        @tool(
            description="decorated",
            parameters={},
            risk="read",
            parallel_safe=True,
            timeout_ms=250,
        )
        async def run(self, _context, _args):
            return {}

    decorated_registry = ToolRegistry()
    Decorated().register(decorated_registry)
    decorated = decorated_registry.list_specs()[0]
    assert decorated.parallel_safe is True
    assert decorated.timeout_ms == 250

    @function_tool(risk="read", parallel_safe=True, timeout_ms=375)
    async def functional(value: str) -> dict[str, str]:
        return {"value": value}

    functional_registry = ToolRegistry()
    functional.register(functional_registry)
    functional_spec = functional_registry.list_specs()[0]
    assert functional_spec.parallel_safe is True
    assert functional_spec.timeout_ms == 375
