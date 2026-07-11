from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import FrozenInstanceError
import logging
import time
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.replay import (
    ApprovalKey,
    SessionState,
    apply_event,
    replay_session,
)
from kaji.infra.events.schemas import (
    KajiEvent,
    ToolCallFailed,
    ToolApprovalApproved,
    ToolApprovalRejected,
    ToolApprovalRequested,
    require_stored_event,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents.approval import (
    ApprovalDecision,
    ApprovalHandler,
    ApprovalRequestContext,
    EventApprovalHandler,
)
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import (
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
from kaji.runtime.providers.mock import MockProvider
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec


def _context(
    token: CancellationToken | None = None,
    *,
    turn_id: str = "turn",
    call_id: str = "call",
) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id="principal",
        session_id="session",
        turn_id=turn_id,
        request_id="request",
        trace_id="trace",
        tool_call_id=call_id,
        idempotency_key=f"session:{call_id}",
        cancellation_token=token or CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


async def _execute(
    handler: ApprovalHandler | None,
    *,
    token: CancellationToken | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[list[KajiEvent], list[dict[str, Any]], AsyncMock]:
    resolved_clock = clock or (lambda: 10.0)
    executor_mock = AsyncMock(return_value={"ok": True})

    async def executor(invocation: ToolInvocation) -> Any:
        return await executor_mock(invocation)

    controller = ToolExecutionController(
        ToolExecutionLimits(approval_timeout_seconds=5),
        clock=resolved_clock,
    )
    planner = ToolPlanner(
        executor,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=handler,
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
        controller=controller,
    )
    events: list[KajiEvent] = []
    journal = InMemoryEventJournal(InMemoryEventStore())

    async def collect(event: KajiEvent) -> None:
        events.append(event)

    emit = JournalEventEmitter(journal, before_commit=collect)

    results = await planner.execute_batch(
        "session",
        [{"id": "call", "name": "charge", "arguments": {"amount": 5}}],
        emit,
        turn_id="turn",
        turn_context=TurnContext(
            principal_id="principal",
            deadline_monotonic=deadline,
        ),
        cancellation_token=token or CancellationToken(),
        approval_journal=journal,
    )
    return events, results, executor_mock


async def _start_external_approval(
    *,
    token: CancellationToken | None = None,
    controller: ToolExecutionController | None = None,
) -> tuple[
    asyncio.Task[list[dict[str, Any]]],
    InMemoryEventStore,
    InMemoryEventJournal,
    CancellationToken,
    AsyncMock,
]:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    resolved_token = token or CancellationToken()
    executor = AsyncMock(return_value={"ok": True})

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=EventApprovalHandler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
        controller=controller,
    )

    emit = JournalEventEmitter(journal)

    pending = asyncio.create_task(
        planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {"amount": 5}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=resolved_token,
            approval_journal=journal,
        )
    )
    while await store.last_sequence("session") < 2:
        await asyncio.sleep(0)
    return pending, store, journal, resolved_token, executor


@pytest.mark.parametrize(
    ("decision", "error_code", "retryable"),
    [
        (
            ApprovalDecision(False, "rejected", "Denied by operator"),
            "APPROVAL_REJECTED",
            False,
        ),
        (
            ApprovalDecision(False, "timeout", "Tool approval timed out"),
            "APPROVAL_TIMEOUT",
            True,
        ),
        (
            ApprovalDecision(False, "cancelled", "Tool approval cancelled"),
            "TOOL_CANCELLED",
            True,
        ),
        (
            ApprovalDecision(False, "unavailable", "Approval unavailable"),
            "APPROVAL_UNAVAILABLE",
            False,
        ),
    ],
)
@pytest.mark.asyncio
async def test_negative_decisions_close_the_exact_lifecycle(
    decision: ApprovalDecision,
    error_code: str,
    retryable: bool,
) -> None:
    class Handler:
        async def request(self, call: object, context: object) -> ApprovalDecision:
            return decision

    events, results, executor = await _execute(Handler())

    assert [event.type for event in events] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_REJECTED,
        EventType.TOOL_CALL_FAILED,
    ]
    rejection = events[2]
    failure = events[3]
    assert isinstance(rejection, ToolApprovalRejected)
    assert isinstance(failure, ToolCallFailed)
    assert rejection.error_code == error_code
    assert failure.error_code == error_code
    assert failure.retryable is retryable
    assert failure.outcome == "not_started"
    assert results[0]["error_code"] == error_code
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_and_throwing_handlers_are_stably_unavailable() -> None:
    class ThrowingHandler:
        async def request(self, call: object, context: object) -> ApprovalDecision:
            raise RuntimeError("secret-approval-infrastructure")

    for handler in (None, ThrowingHandler()):
        events, _, executor = await _execute(handler)
        rejection = events[2]
        assert isinstance(rejection, ToolApprovalRejected)
        assert rejection.error_code == "APPROVAL_UNAVAILABLE"
        assert rejection.reason in {
            "No approval handler registered",
            "Approval handler unavailable",
        }
        executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_backed_pre_cancel_and_deadline_still_emit_request() -> None:
    token = CancellationToken()
    token.cancel()
    cancelled, _, _ = await _execute(
        EventApprovalHandler(),
        token=token,
    )
    assert [event.type for event in cancelled] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_REJECTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert isinstance(cancelled[2], ToolApprovalRejected)
    assert cancelled[2].error_code == "TOOL_CANCELLED"

    expired, _, _ = await _execute(
        EventApprovalHandler(),
        deadline=9.0,
    )
    assert expired[1].type == EventType.TOOL_APPROVAL_REQUESTED
    assert isinstance(expired[2], ToolApprovalRejected)
    assert expired[2].error_code == "APPROVAL_TIMEOUT"


@pytest.mark.asyncio
async def test_event_backed_handler_must_record_its_request() -> None:
    class BrokenEventHandler:
        event_backed = True

        async def request(self, call: object, context: object) -> ApprovalDecision:
            return ApprovalDecision(True, "approved")

    events, _, executor = await _execute(BrokenEventHandler())
    assert [event.type for event in events] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_REJECTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert isinstance(events[2], ToolApprovalRejected)
    assert events[2].error_code == "APPROVAL_UNAVAILABLE"
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_planner_enforces_handler_timeout_and_caller_cancellation() -> None:
    class HangingHandler:
        async def request(self, call: object, context: object) -> ApprovalDecision:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    times = iter((9.0, 9.0, 10.0))
    timed_out, _, executor = await _execute(
        HangingHandler(),
        deadline=10.0,
        clock=lambda: next(times, 10.0),
    )
    assert isinstance(timed_out[2], ToolApprovalRejected)
    assert timed_out[2].error_code == "APPROVAL_TIMEOUT"
    executor.assert_not_awaited()

    token = CancellationToken()
    task = asyncio.create_task(_execute(HangingHandler(), token=token))
    await asyncio.sleep(0)
    token.cancel()
    cancelled, _, executor = await task
    assert isinstance(cancelled[2], ToolApprovalRejected)
    assert cancelled[2].error_code == "TOOL_CANCELLED"
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_rejection_is_not_duplicated_by_planner() -> None:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    executor = AsyncMock(return_value={"ok": True})

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=EventApprovalHandler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
    )

    emit = JournalEventEmitter(journal)

    pending = asyncio.create_task(
        planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
    )
    while await store.last_sequence("session") < 2:
        await asyncio.sleep(0)
    await journal.commit(
        ToolApprovalRejected(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
            error_code="APPROVAL_REJECTED",
            reason="Denied externally",
        )
    )
    results = await pending
    events = await store.get_events("session")

    assert [event.type for event in events] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_REJECTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert results[0]["error_code"] == "APPROVAL_REJECTED"
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_decision_uses_runtime_journal_emitter_and_tri_key() -> None:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    tool_context = _context()
    call = ToolInvocation(name="charge", arguments={"amount": 5}, context=tool_context)
    emitted: list[KajiEvent] = []

    async def request() -> Any:
        event = ToolApprovalRequested(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
            tool_args={"amount": 5},
            risk="destructive",
        )
        emitted.append(event)
        return await journal.commit(event)

    async def observe(event: Any) -> None:
        _ = event

    request_context = ApprovalRequestContext(
        tool_context=tool_context,
        risk="destructive",
        arguments=call.arguments,
        journal=journal,
        request=request,
        observe=observe,
        deadline_monotonic=100.0,
    )
    handler = EventApprovalHandler()
    pending = asyncio.create_task(handler.request(call, request_context))
    while await store.last_sequence("session") == 0:
        await asyncio.sleep(0)

    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="wrong-turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )
    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="wrong-name",
            tool_call_id="call",
        )
    )
    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )

    assert await pending == ApprovalDecision(True, "approved", recorded=True)
    assert [event.type for event in emitted] == [EventType.TOOL_APPROVAL_REQUESTED]
    assert journal._subscribers == {}


@pytest.mark.asyncio
async def test_event_handler_ignores_matching_decision_before_exact_request() -> None:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    tool_context = _context()
    call = ToolInvocation(name="charge", arguments={"amount": 5}, context=tool_context)
    observed: list[Any] = []

    async def request() -> Any:
        await journal.commit(
            ToolApprovalApproved(
                session_id="session",
                turn_id="turn",
                tool_name="charge",
                tool_call_id="call",
            )
        )
        return await journal.commit(
            ToolApprovalRequested(
                session_id="session",
                turn_id="turn",
                tool_name="charge",
                tool_call_id="call",
                tool_args={"amount": 5},
                risk="destructive",
            )
        )

    async def observe(event: Any) -> None:
        observed.append(event)

    context = ApprovalRequestContext(
        tool_context=tool_context,
        risk="destructive",
        arguments=call.arguments,
        journal=journal,
        request=request,
        observe=observe,
        deadline_monotonic=100,
    )
    pending = asyncio.create_task(EventApprovalHandler().request(call, context))
    while await store.last_sequence("session") < 2:
        await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not pending.done()
    fresh = await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )

    assert await pending == ApprovalDecision(True, "approved", recorded=True)
    assert [event.id for event in observed] == [fresh.id]


@pytest.mark.asyncio
async def test_handler_cannot_mutate_or_duplicate_canonical_request() -> None:
    duplicate_errors: list[BaseException] = []

    class AdversarialHandler:
        event_backed = True

        async def request(
            self,
            call: ToolInvocation,
            context: ApprovalRequestContext,
        ) -> ApprovalDecision:
            with pytest.raises(TypeError):
                cast(Any, context.arguments)["amount"] = 999
            with pytest.raises(TypeError):
                cast(Any, call.arguments)["amount"] = 999
            with pytest.raises(TypeError):
                cast(Any, context.tool_context.metadata)["role"] = "admin"
            with pytest.raises(FrozenInstanceError):
                cast(Any, context).risk = "read"
            await context.request()
            try:
                await context.request()
            except BaseException as error:
                duplicate_errors.append(error)
            with pytest.raises(TypeError):
                await cast(Any, context.request)(object())
            return ApprovalDecision(True, "approved")

    events, _, executor = await _execute(AdversarialHandler())
    requests = [
        event for event in events if event.type == EventType.TOOL_APPROVAL_REQUESTED
    ]
    assert len(requests) == 1
    assert isinstance(requests[0], ToolApprovalRequested)
    assert requests[0].tool_args == {"amount": 5}
    assert requests[0].risk == "destructive"
    assert requests[0].metadata == {}
    assert len(duplicate_errors) == 1
    assert isinstance(duplicate_errors[0], RuntimeError)
    executor.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_resistant_handler_is_owned_until_it_settles() -> None:
    release = asyncio.Event()
    started = asyncio.Event()
    late_errors: list[BaseException] = []

    class ResistantHandler:
        async def request(
            self,
            call: ToolInvocation,
            context: ApprovalRequestContext,
        ) -> ApprovalDecision:
            _ = call
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                try:
                    await context.request()
                except BaseException as error:
                    late_errors.append(error)
                return ApprovalDecision(True, "approved")
            raise AssertionError("approval wait returned without cancellation")

    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    controller = ToolExecutionController(
        ToolExecutionLimits(max_parallel=1, approval_timeout_seconds=0.01),
        clock=time.monotonic,
    )
    executor = AsyncMock(return_value={"ok": True})

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=ResistantHandler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
        controller=controller,
    )

    emit = JournalEventEmitter(journal)

    pending = asyncio.create_task(
        planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
    )
    await started.wait()
    results = await pending
    assert results[0]["error_code"] == "APPROVAL_TIMEOUT"
    assert await controller.drain_tools(0) == ["call"]
    release.set()
    assert await controller.drain_tools(1) == []
    assert len(late_errors) == 1
    assert isinstance(late_errors[0], RuntimeError)
    events = await store.get_events("session")
    assert sum(event.type == EventType.TOOL_APPROVAL_REQUESTED for event in events) == 1
    assert all(event.type != EventType.TOOL_APPROVAL_APPROVED for event in events)


@pytest.mark.asyncio
async def test_durable_decision_wins_simultaneous_cancellation() -> None:
    pending, store, journal, token, executor = await _start_external_approval()
    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )
    token.cancel()

    results = await pending
    assert results[0]["error_code"] == "TOOL_CANCELLED"
    events = await store.get_events("session")
    assert sum(event.type == EventType.TOOL_APPROVAL_APPROVED for event in events) == 1
    assert all(event.type != EventType.TOOL_APPROVAL_REJECTED for event in events)
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_before_decision_has_one_terminal_outcome() -> None:
    pending, store, _, token, executor = await _start_external_approval()
    token.cancel()

    results = await pending
    assert results[0]["error_code"] == "TOOL_CANCELLED"
    events = await store.get_events("session")
    rejections = [
        event for event in events if event.type == EventType.TOOL_APPROVAL_REJECTED
    ]
    assert len(rejections) == 1
    assert rejections[0].error_code == "TOOL_CANCELLED"
    assert all(event.type != EventType.TOOL_APPROVAL_APPROVED for event in events)
    executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_handler_uses_controller_clock_domain() -> None:
    controller = ToolExecutionController(
        ToolExecutionLimits(approval_timeout_seconds=5),
        clock=lambda: 1_000_000.0,
    )
    pending, _, journal, _, executor = await _start_external_approval(
        controller=controller
    )
    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )
    results = await pending
    assert results[0]["result"] == {"ok": True}
    executor.assert_awaited_once()


@pytest.mark.asyncio
async def test_framework_timeout_fence_selects_lower_sequence_external_decision() -> (
    None
):
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    fence_waiting = asyncio.Event()
    release_fence = asyncio.Event()
    executor = AsyncMock(return_value={"ok": True})

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    async def pause_fence(event: KajiEvent) -> None:
        if (
            isinstance(event, ToolApprovalRejected)
            and event.error_code == "APPROVAL_TIMEOUT"
        ):
            fence_waiting.set()
            await release_fence.wait()

    emitter = JournalEventEmitter(journal, before_commit=pause_fence)
    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=EventApprovalHandler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
        controller=ToolExecutionController(
            ToolExecutionLimits(approval_timeout_seconds=0.01),
            clock=time.monotonic,
        ),
    )
    pending = asyncio.create_task(
        planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {}}],
            emitter,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=journal,
        )
    )
    await asyncio.wait_for(fence_waiting.wait(), timeout=1)
    external = await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )
    release_fence.set()
    results = await pending
    events = await store.get_events("session")

    assert results[0]["result"] == {"ok": True}
    decisions = [
        event
        for event in events
        if event.type
        in (
            EventType.TOOL_APPROVAL_APPROVED,
            EventType.TOOL_APPROVAL_REJECTED,
        )
    ]
    assert decisions[0].id == external.id
    assert [event.type for event in decisions] == [
        EventType.TOOL_APPROVAL_APPROVED,
        EventType.TOOL_APPROVAL_REJECTED,
    ]
    assert events[-1].type == EventType.TOOL_CALL_COMPLETED
    replayed = replay_session(events)
    key = ApprovalKey("turn", "call", "charge")
    assert replayed.approved_approvals == {key}
    assert key not in replayed.rejected_approvals
    executor.assert_awaited_once()


@pytest.mark.parametrize("external_approved", [True, False])
@pytest.mark.asyncio
async def test_observed_decision_overrides_mismatched_unrecorded_return(
    external_approved: bool,
) -> None:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    executor = AsyncMock(return_value={"ok": True})

    class Handler:
        event_backed = True

        async def request(
            self,
            call: ToolInvocation,
            context: ApprovalRequestContext,
        ) -> ApprovalDecision:
            await context.request()
            if external_approved:
                event = ToolApprovalApproved(
                    session_id=call.context.session_id,
                    turn_id=call.context.turn_id,
                    tool_name=call.name,
                    tool_call_id=call.context.tool_call_id,
                )
                mismatched = ApprovalDecision(
                    False,
                    "rejected",
                    "Mismatched local rejection",
                )
            else:
                event = ToolApprovalRejected(
                    session_id=call.context.session_id,
                    turn_id=call.context.turn_id,
                    tool_name=call.name,
                    tool_call_id=call.context.tool_call_id,
                    error_code="APPROVAL_REJECTED",
                    reason="Durable external rejection",
                )
                mismatched = ApprovalDecision(True, "approved")
            stored = await context.journal.commit(event)
            await context.observe(stored)
            return mismatched

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=Handler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
    )
    results = await planner.execute_batch(
        "session",
        [{"id": "call", "name": "charge", "arguments": {}}],
        JournalEventEmitter(journal),
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
        approval_journal=journal,
    )
    events = await store.get_events("session")
    approval_events = [
        event
        for event in events
        if event.type
        in (
            EventType.TOOL_APPROVAL_APPROVED,
            EventType.TOOL_APPROVAL_REJECTED,
        )
    ]
    assert len(approval_events) == 1
    if external_approved:
        assert results[0]["result"] == {"ok": True}
        assert approval_events[0].type == EventType.TOOL_APPROVAL_APPROVED
        executor.assert_awaited_once()
    else:
        assert results[0]["error_code"] == "APPROVAL_REJECTED"
        assert approval_events[0].type == EventType.TOOL_APPROVAL_REJECTED
        executor.assert_not_awaited()


@pytest.mark.asyncio
async def test_mismatched_approval_journal_and_emitter_are_rejected() -> None:
    store = InMemoryEventStore()
    canonical = InMemoryEventJournal(store)
    foreign = InMemoryEventJournal(store)

    class Handler:
        async def request(self, call: object, context: object) -> ApprovalDecision:
            return ApprovalDecision(True, "approved")

    executor = AsyncMock(return_value={"ok": True})

    async def execute(invocation: ToolInvocation) -> Any:
        return await executor(invocation)

    planner = ToolPlanner(
        execute,
        policy=ToolPolicy(require_approval_for={"destructive"}),
        approval_handler=Handler(),
        specs={
            "charge": ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )
        },
    )

    emit = JournalEventEmitter(foreign)

    with pytest.raises(ValueError, match="explicitly bound"):
        await planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {}}],
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=canonical,
        )
    assert await canonical.store.last_sequence("session") == 0
    assert await foreign.store.last_sequence("session") == 0

    async def bare_emit(event: KajiEvent) -> Any:
        return await canonical.commit(event)

    with pytest.raises(ValueError, match="explicitly bound"):
        await planner.execute_batch(
            "session",
            [{"id": "call", "name": "charge", "arguments": {}}],
            bare_emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
            approval_journal=canonical,
        )
    assert await store.last_sequence("session") == 0


@pytest.mark.asyncio
async def test_approval_subscription_closes_exactly_once_and_fails_unclosable() -> None:
    inner = InMemoryEventJournal(InMemoryEventStore())
    closes = 0

    class CountingSubscription:
        def __init__(self, subscription: Any) -> None:
            self._subscription = subscription

        def __aiter__(self) -> Any:
            return self

        async def __anext__(self) -> Any:
            return await anext(self._subscription)

        async def aclose(self) -> None:
            nonlocal closes
            closes += 1
            await self._subscription.aclose()

    class CountingJournal:
        store = inner.store

        async def commit(self, event: Any) -> Any:
            return await inner.commit(event)

        async def open_subscription(self, *args: Any, **kwargs: Any) -> Any:
            return CountingSubscription(await inner.open_subscription(*args, **kwargs))

        def subscribe(self, *args: Any, **kwargs: Any) -> Any:
            return inner.subscribe(*args, **kwargs)

    journal = CountingJournal()
    tool_context = _context()
    call = ToolInvocation(name="charge", arguments={}, context=tool_context)

    async def request() -> Any:
        return await journal.commit(
            ToolApprovalRequested(
                session_id="session",
                turn_id="turn",
                tool_name="charge",
                tool_call_id="call",
                tool_args={},
                risk="destructive",
            )
        )

    async def observe(event: Any) -> None:
        _ = event

    context = ApprovalRequestContext(
        tool_context=tool_context,
        risk="destructive",
        arguments={},
        journal=journal,  # type: ignore[arg-type]
        request=request,
        observe=observe,
        deadline_monotonic=100,
    )
    pending = asyncio.create_task(EventApprovalHandler().request(call, context))
    while await inner.store.last_sequence("session") < 1:
        await asyncio.sleep(0)
    await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
        )
    )
    assert (await pending).granted
    assert closes == 1

    class Unclosable:
        def __aiter__(self) -> Any:
            return self

        async def __anext__(self) -> Any:
            await asyncio.Event().wait()

    class BrokenJournal(CountingJournal):
        async def open_subscription(self, *args: Any, **kwargs: Any) -> Any:
            return Unclosable()

    broken_context = ApprovalRequestContext(
        tool_context=tool_context,
        risk="destructive",
        arguments={},
        journal=BrokenJournal(),  # type: ignore[arg-type]
        request=request,
        observe=observe,
        deadline_monotonic=100,
    )
    with pytest.raises(TypeError, match="explicitly closable"):
        await EventApprovalHandler().request(call, broken_context)


@pytest.mark.asyncio
async def test_external_decision_is_once_and_contiguous_in_turn_result() -> None:
    class ChargeIntegration:
        def register(self, registry: ToolRegistry) -> None:
            spec = ToolSpec(
                name="charge",
                description="charge",
                parameters={},
                risk="destructive",
            )

            @registry.register(spec)
            async def charge(
                context: Any, arguments: dict[str, Any]
            ) -> dict[str, bool]:
                _ = (context, arguments)
                return {"charged": True}

    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)
    runtime = (
        AgentBuilder()
        .provider(MockProvider(tool_call={"name": "charge", "args": {}}))
        .integration(ChargeIntegration())
        .policy(ToolPolicy(require_approval_for={"destructive"}))
        .approval_handler(EventApprovalHandler())
        .build(store=store, journal=journal)
    )
    pending = asyncio.create_task(
        runtime.turn(
            "charge",
            session_id="session",
            context=TurnContext(principal_id="principal"),
        )
    )
    requested: ToolApprovalRequested | None = None
    while requested is None:
        events = await store.get_events("session")
        requested = next(
            (event for event in events if isinstance(event, ToolApprovalRequested)),
            None,
        )
        if requested is None:
            await asyncio.sleep(0)
    external = await journal.commit(
        ToolApprovalApproved(
            session_id="session",
            turn_id=requested.turn_id,
            tool_name=requested.tool_name,
            tool_call_id=requested.tool_call_id,
        )
    )
    result = await pending

    assert sum(event.id == external.id for event in result.events) == 1
    assert [event.sequence for event in result.events] == list(
        range(1, len(result.events) + 1)
    )
    stored = await store.get_events("session")
    assert [event.id for event in result.events] == [event.id for event in stored]


@pytest.mark.asyncio
async def test_throwing_logger_cannot_escape_handler_normalization() -> None:
    class ExplodingLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("logging unavailable")

    class ThrowingHandler:
        async def request(self, call: object, context: object) -> ApprovalDecision:
            raise RuntimeError("approval unavailable")

    logger = logging.getLogger("kaji.runtime.agents.planner")
    previous_handlers = logger.handlers[:]
    previous_propagate = logger.propagate
    logger.handlers = [ExplodingLogHandler()]
    logger.propagate = False
    try:
        events, results, executor = await _execute(ThrowingHandler())
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagate

    assert results[0]["error_code"] == "APPROVAL_UNAVAILABLE"
    assert isinstance(events[2], ToolApprovalRejected)
    executor.assert_not_awaited()


def _stored(*events: KajiEvent) -> list[Any]:
    return [
        require_stored_event(event.model_copy(update={"sequence": index}))
        for index, event in enumerate(events, start=1)
    ]


def test_replay_approval_keys_are_tri_keyed_and_incremental_matches_cold() -> None:
    events = _stored(
        ToolApprovalRequested(
            session_id="session",
            turn_id="turn-a",
            tool_name="charge",
            tool_call_id="same-call",
            tool_args={},
            risk="destructive",
        ),
        ToolApprovalRequested(
            session_id="session",
            turn_id="turn-b",
            tool_name="refund",
            tool_call_id="same-call",
            tool_args={},
            risk="destructive",
        ),
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn-a",
            tool_name="charge",
            tool_call_id="same-call",
        ),
        ToolApprovalRejected(
            session_id="session",
            turn_id="turn-b",
            tool_name="refund",
            tool_call_id="same-call",
            error_code="APPROVAL_TIMEOUT",
            reason="Tool approval timed out",
        ),
        ToolApprovalRejected(
            session_id="session",
            turn_id="turn-a",
            tool_name="charge",
            tool_call_id="same-call",
            error_code="APPROVAL_REJECTED",
            reason="Late opposite decision",
        ),
        ToolApprovalApproved(
            session_id="session",
            turn_id="turn-b",
            tool_name="refund",
            tool_call_id="same-call",
        ),
    )
    cold = replay_session(events)
    warm = SessionState(session_id="session")
    for event in events:
        apply_event(warm, event)

    assert warm == cold
    assert cold.pending_approvals == set()
    assert cold.approved_approvals == {ApprovalKey("turn-a", "same-call", "charge")}
    assert cold.rejected_approvals == {
        ApprovalKey("turn-b", "same-call", "refund"): "APPROVAL_TIMEOUT"
    }


def test_approval_decision_and_context_invariants_are_bounded() -> None:
    with pytest.raises(ValueError, match="closed approval vocabulary"):
        ApprovalDecision(False, cast(Any, "maybe"), "unknown")
    with pytest.raises(ValueError, match="granted"):
        ApprovalDecision(True, "rejected", "no")
    with pytest.raises(ValueError, match="non-empty"):
        ApprovalDecision(False, "rejected", " ")
    with pytest.raises(ValueError, match="200"):
        ApprovalDecision(False, "rejected", "x" * 201)

    tool_context = _context()
    journal = InMemoryEventJournal(InMemoryEventStore())

    async def request() -> Any:
        event = ToolApprovalRequested(
            session_id="session",
            turn_id="turn",
            tool_name="charge",
            tool_call_id="call",
            tool_args={},
            risk="destructive",
        )
        return await journal.commit(event)

    async def observe(event: Any) -> None:
        _ = event

    with pytest.raises(ValueError, match="canonical risk"):
        ApprovalRequestContext(
            tool_context=tool_context,
            risk=cast(Any, "secret-dependent-risk"),
            arguments={},
            journal=journal,
            request=request,
            observe=observe,
            deadline_monotonic=1,
        )
