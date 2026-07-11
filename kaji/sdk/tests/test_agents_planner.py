import pytest

from kaji.infra.events.journal import InMemoryEventJournal
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
from kaji.infra.events.schemas import (
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
)
from kaji.infra.events.types import EventType
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolSpec


_TURN_CONTEXT = TurnContext(principal_id="test-principal")


async def _execute(planner, session_id, calls, emit):
    journal = InMemoryEventJournal(InMemoryEventStore())

    async def collect(event):
        await emit(event)

    commit = JournalEventEmitter(journal, before_commit=collect)

    return await planner.execute_scatter_gather(
        session_id,
        calls,
        commit,
        turn_id="test-turn",
        turn_context=_TURN_CONTEXT,
        cancellation_token=CancellationToken(),
        approval_journal=journal,
    )


@pytest.mark.asyncio
async def test_tool_planner_emits_lifecycle_on_success():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(name: str, args: dict):
        return {"ok": True, "name": name, "args": args}

    planner = ToolPlanner(
        executor=executor,
        specs={
            "search": ToolSpec(
                name="search", description="search", parameters={}, risk="read"
            )
        },
    )
    await _execute(
        planner,
        "sess-1",
        [{"id": "call-1", "name": "search", "arguments": {"q": "test"}}],
        emit,
    )

    types = [event.type for event in emitted]
    assert types == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
    ]
    assert isinstance(emitted[0], ToolCallRequested)
    assert isinstance(emitted[-1], ToolCallCompleted)


@pytest.mark.asyncio
async def test_tool_planner_emits_failure_event():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        raise RuntimeError("tool exploded")

    planner = ToolPlanner(
        executor=executor,
        specs={
            "broken": ToolSpec(
                name="broken", description="broken", parameters={}, risk="read"
            )
        },
    )
    results = await _execute(
        planner,
        "sess-1",
        [{"id": "call-2", "name": "broken", "arguments": {}}],
        emit,
    )

    assert results[0] == {
        "id": "call-2",
        "name": "broken",
        "error": "Tool execution failed",
        "error_code": "TOOL_EXECUTION_FAILED",
        "retryable": False,
        "outcome": "unknown",
    }
    assert any(event.type == EventType.TOOL_CALL_FAILED for event in emitted)
    assert isinstance(
        next(event for event in emitted if event.type == EventType.TOOL_CALL_FAILED),
        ToolCallFailed,
    )


@pytest.mark.asyncio
async def test_tool_planner_generates_call_id_when_missing():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def _ok_executor(_name: str, _args: dict) -> str:
        return "ok"

    planner = ToolPlanner(
        executor=_ok_executor,
        specs={
            "search": ToolSpec(
                name="search", description="search", parameters={}, risk="read"
            )
        },
    )
    await _execute(
        planner,
        "sess-1",
        [{"name": "search", "arguments": {}}],
        emit,
    )
    started = next(
        event for event in emitted if event.type == EventType.TOOL_CALL_STARTED
    )
    assert isinstance(started, ToolCallStarted)
    assert started.tool_call_id


# --- Approval gate tests ---


@pytest.mark.asyncio
async def test_approval_approved_proceeds_to_execution():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        return {"ok": True}

    async def approve(_name, _args, _risk):
        return True

    policy = ToolPolicy(require_approval_for={"destructive"})
    spec = ToolSpec(name="nuke", description="nuke", parameters={}, risk="destructive")
    planner = ToolPlanner(
        executor=executor,
        policy=policy,
        approval_handler=approve,
        specs={"nuke": spec},
    )
    results = await _execute(
        planner,
        "sess-approval",
        [{"id": "c1", "name": "nuke", "arguments": {}}],
        emit,
    )

    types = [e.type for e in emitted]
    assert EventType.TOOL_APPROVAL_REQUESTED in types
    assert EventType.TOOL_APPROVAL_APPROVED in types
    assert EventType.TOOL_CALL_COMPLETED in types
    assert results[0]["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_approval_rejected_skips_execution():
    emitted = []
    executor_called = False

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        nonlocal executor_called
        executor_called = True
        return {"ok": True}

    async def reject(_name, _args, _risk):
        return False

    policy = ToolPolicy(require_approval_for={"financial"})
    spec = ToolSpec(
        name="charge", description="charge card", parameters={}, risk="financial"
    )
    planner = ToolPlanner(
        executor=executor,
        policy=policy,
        approval_handler=reject,
        specs={"charge": spec},
    )
    results = await _execute(
        planner,
        "sess-reject",
        [{"id": "c2", "name": "charge", "arguments": {}}],
        emit,
    )

    assert not executor_called, "executor must not be called when approval is rejected"
    types = [e.type for e in emitted]
    assert EventType.TOOL_APPROVAL_REQUESTED in types
    assert EventType.TOOL_APPROVAL_REJECTED in types
    assert EventType.TOOL_CALL_STARTED not in types
    assert "error" in results[0]


@pytest.mark.asyncio
async def test_no_approval_needed_for_unclassified_risk():
    """Tools with no policy or low-risk specs skip the approval gate entirely."""
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        return {"ok": True}

    policy = ToolPolicy(require_approval_for={"destructive"})
    spec = ToolSpec(name="search", description="search", parameters={}, risk="read")
    planner = ToolPlanner(
        executor=executor,
        policy=policy,
        specs={"search": spec},
    )
    await _execute(
        planner,
        "sess-no-approval",
        [{"id": "c3", "name": "search", "arguments": {}}],
        emit,
    )

    types = [e.type for e in emitted]
    assert EventType.TOOL_APPROVAL_REQUESTED not in types
    assert EventType.TOOL_CALL_COMPLETED in types


@pytest.mark.asyncio
async def test_no_approval_handler_rejects_by_default():
    """When approval is required but no handler is provided, execution is rejected."""
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        return {"ok": True}

    policy = ToolPolicy(require_approval_for={"admin"})
    spec = ToolSpec(
        name="add_user", description="add user", parameters={}, risk="admin"
    )
    planner = ToolPlanner(
        executor=executor,
        policy=policy,
        approval_handler=None,
        specs={"add_user": spec},
    )
    results = await _execute(
        planner,
        "sess-no-handler",
        [{"id": "c4", "name": "add_user", "arguments": {}}],
        emit,
    )

    types = [e.type for e in emitted]
    assert EventType.TOOL_APPROVAL_REJECTED in types
    assert EventType.TOOL_CALL_STARTED not in types
    assert "error" in results[0]


@pytest.mark.asyncio
async def test_policy_denied_tool_skips_execution_and_approval():
    emitted = []
    called = {"executor": False, "approval": False}

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        called["executor"] = True
        return {"ok": True}

    async def approve(_name, _args, _risk):
        called["approval"] = True
        return True

    policy = ToolPolicy(denied={"delete"}, require_approval_for={"destructive"})
    spec = ToolSpec(
        name="delete",
        description="delete",
        parameters={},
        risk="destructive",
    )
    planner = ToolPlanner(
        executor=executor,
        policy=policy,
        approval_handler=approve,
        specs={"delete": spec},
    )

    results = await _execute(
        planner,
        "sess-denied",
        [{"id": "c5", "name": "delete", "arguments": {}}],
        emit,
    )

    assert called["executor"] is False
    assert called["approval"] is False
    types = [event.type for event in emitted]
    assert types == [EventType.TOOL_CALL_REQUESTED, EventType.TOOL_CALL_FAILED]
    assert results[0] == {
        "id": "c5",
        "name": "delete",
        "error": "Tool not permitted",
        "error_code": "TOOL_NOT_ALLOWED",
        "retryable": False,
        "outcome": "not_started",
    }


@pytest.mark.asyncio
async def test_policy_allowlist_blocks_unlisted_tool():
    emitted = []
    called = {"executor": False}

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        called["executor"] = True
        return {"ok": True}

    planner = ToolPlanner(
        executor=executor,
        policy=ToolPolicy(allowed={"search"}),
        specs={
            "charge": ToolSpec(
                name="charge", description="charge", parameters={}, risk="financial"
            )
        },
    )

    results = await _execute(
        planner,
        "sess-allowlist",
        [{"id": "c6", "name": "charge", "arguments": {}}],
        emit,
    )

    assert called["executor"] is False
    assert [event.type for event in emitted] == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert results[0] == {
        "id": "c6",
        "name": "charge",
        "error": "Tool not permitted",
        "error_code": "TOOL_NOT_ALLOWED",
        "retryable": False,
        "outcome": "not_started",
    }
