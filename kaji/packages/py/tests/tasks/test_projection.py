import asyncio

import pytest

from kaji.artifacts import ArtifactRef
from kaji.events.schemas import (
    AgentTurnFailed,
    ArtifactEmitted,
    TaskCompleted,
    ToolApprovalApproved,
    ToolApprovalRequested,
    ToolCallFailed,
)
from kaji.tasks import InMemoryBackend, TaskRuntime, TaskState


async def _task():
    backend = InMemoryBackend.create()
    runtime = TaskRuntime(backend)
    handle = await runtime.start(session_id="session", principal_id="principal", input="hello", task_id="task")
    return backend, handle


@pytest.mark.asyncio
async def test_projection_lifecycle_and_history_cursor():
    backend, handle = await _task()
    assert (await handle.snapshot()).state is TaskState.RUNNING
    await backend.journal.commit(TaskCompleted(id="complete", task_id="task", session_id="session"))
    snapshot = await handle.snapshot()
    assert snapshot.state is TaskState.COMPLETED
    assert snapshot.sequence_cursor == 3
    assert [event.sequence for event in await handle.events(after_sequence=1)] == [2, 3]


@pytest.mark.asyncio
async def test_projection_approval_unknown_failure_and_artifact_order():
    backend, handle = await _task()
    await backend.journal.commit(ToolApprovalRequested(id="approval", session_id="session", turn_id="turn", tool_name="write", tool_call_id="call", tool_args={"secret": "not-in-snapshot"}, risk="write"))
    snapshot = await handle.snapshot()
    assert snapshot.state is TaskState.WAITING_FOR_APPROVAL
    assert not hasattr(snapshot.pending_approvals[0], "arguments")
    approval = (await handle.pending_approvals())[0]
    await backend.journal.commit(ToolApprovalApproved(id="approved", session_id="session", turn_id="turn", tool_name="write", tool_call_id="call"))
    assert (await handle.snapshot()).state is TaskState.RUNNING
    await backend.journal.commit(ArtifactEmitted(id="artifact-a", session_id="session", turn_id="turn", tool_call_id="call", artifact=ArtifactRef(id="first", type="text/plain", uri="memory:first")))
    await backend.journal.commit(ArtifactEmitted(id="artifact-b", session_id="session", turn_id="turn", tool_call_id="call", artifact=ArtifactRef(id="second", type="text/plain", uri="memory:second")))
    assert [artifact.id for artifact in (await handle.snapshot()).artifacts] == ["first", "second"]
    await backend.journal.commit(ToolCallFailed(id="unknown", session_id="session", turn_id="turn", tool_name="write", tool_call_id="call", error="unknown", outcome="unknown"))
    assert (await handle.snapshot()).state is TaskState.RECONCILIATION_REQUIRED
    assert approval.capability == "write"


@pytest.mark.asyncio
async def test_provider_failure_and_cancellation_project_terminal_states():
    backend, handle = await _task()
    await backend.journal.commit(AgentTurnFailed(id="failed", session_id="session", turn_id="turn", error="provider", error_code="PROVIDER"))
    assert (await handle.snapshot()).state is TaskState.FAILED
    _, cancel_handle = await _task()
    assert (await cancel_handle.cancel()).state is TaskState.CANCELLED


@pytest.mark.asyncio
async def test_tasks_on_separate_sessions_do_not_block_each_other():
    backend = InMemoryBackend.create()
    runtime = TaskRuntime(backend)
    first, second = await asyncio.gather(
        runtime.start(session_id="one", principal_id="p", input="one", task_id="one"),
        runtime.start(session_id="two", principal_id="p", input="two", task_id="two"),
    )
    assert (await first.snapshot()).state is TaskState.RUNNING
    assert (await second.snapshot()).state is TaskState.RUNNING
