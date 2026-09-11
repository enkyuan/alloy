"""Journal-only task state projection."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from kaji.artifacts import ArtifactRef
from kaji.events.schemas import StoredKajiEvent
from kaji.events.types import EventType
from kaji.runtime.sessions.replay import replay_session

from .errors import InvalidTaskTransitionError, TaskProjectionError
from .types import PendingApproval, PendingApprovalSummary, TaskSnapshot, TaskState


_TERMINAL = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
_ACTIVITY = {
    EventType.SESSION_CREATED,
    EventType.USER_MESSAGE,
    EventType.AGENT_REASONING_STARTED,
    EventType.TOOL_CALL_REQUESTED,
    EventType.TOOL_CALL_STARTED,
    EventType.TOOL_CALL_COMPLETED,
}


def approval_id(event: StoredKajiEvent) -> str:
    return f"{event.turn_id}:{event.tool_call_id}"  # type: ignore[attr-defined]


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _transition(current: TaskState, target: TaskState) -> TaskState:
    if current in _TERMINAL:
        raise InvalidTaskTransitionError(
            f"cannot transition terminal task from {current} to {target}"
        )
    if target is TaskState.SUSPENDED and current not in {
        TaskState.RUNNING,
        TaskState.WAITING_FOR_APPROVAL,
        TaskState.RECONCILIATION_REQUIRED,
    }:
        raise InvalidTaskTransitionError(f"cannot suspend task from {current}")
    if target is TaskState.RUNNING and current not in {
        TaskState.CREATED,
        TaskState.SUSPENDED,
        TaskState.WAITING_FOR_APPROVAL,
        TaskState.RECONCILIATION_REQUIRED,
    }:
        raise InvalidTaskTransitionError(f"cannot resume task from {current}")
    return target


def project_task(task_id: str, events: Iterable[StoredKajiEvent]) -> TaskSnapshot:
    """Return the control-plane snapshot derived only from stored events."""

    events = tuple(events)
    state: TaskState | None = None
    created_at: str | None = None
    updated_at: str | None = None
    cursor = 0
    artifacts: dict[str, ArtifactRef] = {}
    pending: dict[str, PendingApproval] = {}
    terminal_error_code: str | None = None
    previous_sequence = 0

    for event in events:
        if event.sequence <= previous_sequence:
            raise TaskProjectionError("task events must be in ascending sequence order")
        previous_sequence = event.sequence
        event_task_id = getattr(event, "task_id", None)
        if event.type is EventType.TASK_CREATED:
            if event_task_id != task_id:
                continue
            if state is not None:
                raise TaskProjectionError(f"duplicate task.created for {task_id}")
            state = TaskState.CREATED
            created_at = _timestamp(event.timestamp)
        elif state is None:
            continue
        elif event_task_id is not None and event_task_id != task_id:
            continue
        elif event.type is EventType.TASK_SUSPENDED:
            state = _transition(state, TaskState.SUSPENDED)
        elif event.type is EventType.TASK_RESUMED:
            state = _transition(state, TaskState.RUNNING)
        elif event.type is EventType.TASK_COMPLETED:
            state = _transition(state, TaskState.COMPLETED)
        elif event.type is EventType.TASK_FAILED:
            state = _transition(state, TaskState.FAILED)
            terminal_error_code = getattr(event, "error_code", None)
        elif event.type is EventType.TASK_CANCELLED:
            state = _transition(state, TaskState.CANCELLED)
        elif event.type is EventType.TOOL_APPROVAL_REQUESTED:
            pending[approval_id(event)] = PendingApproval(
                id=approval_id(event),
                capability=event.tool_name,
                risk=event.risk,
                arguments=dict(event.tool_args),
            )
            if (
                state not in _TERMINAL
                and state is not TaskState.RECONCILIATION_REQUIRED
            ):
                state = TaskState.WAITING_FOR_APPROVAL
        elif event.type in {
            EventType.TOOL_APPROVAL_APPROVED,
            EventType.TOOL_APPROVAL_REJECTED,
        }:
            pending.pop(approval_id(event), None)
            if state is TaskState.WAITING_FOR_APPROVAL:
                state = TaskState.RUNNING
        elif event.type is EventType.TOOL_CALL_FAILED and event.outcome == "unknown":
            if state not in _TERMINAL:
                state = TaskState.RECONCILIATION_REQUIRED
        elif event.type is EventType.AGENT_TURN_FAILED:
            if (
                state not in _TERMINAL
                and state is not TaskState.RECONCILIATION_REQUIRED
            ):
                state = TaskState.FAILED
                terminal_error_code = event.error_code
        elif event.type is EventType.CANCELLATION_COMPLETED:
            if (
                state not in _TERMINAL
                and state is not TaskState.RECONCILIATION_REQUIRED
            ):
                state = TaskState.CANCELLED
        elif event.type in _ACTIVITY and state is TaskState.CREATED:
            state = TaskState.RUNNING

        if event.type is EventType.ARTIFACT_EMITTED:
            artifact = ArtifactRef.model_validate(event.artifact)
            current = artifacts.get(artifact.id)
            if current is not None and current != artifact:
                raise TaskProjectionError(f"conflicting artifact id {artifact.id}")
            artifacts[artifact.id] = artifact
        cursor = event.sequence
        updated_at = _timestamp(event.timestamp)

    if state is None or created_at is None or updated_at is None:
        raise TaskProjectionError(f"task {task_id} was not created in this journal")

    replay = replay_session(events)
    pending_summaries = tuple(
        PendingApprovalSummary(id=item.id, capability=item.capability, risk=item.risk)
        for item in pending.values()
    )
    # Replay is the canonical source of approval resolution; retain only requests it marks pending.
    pending_summaries = tuple(
        item
        for item in pending_summaries
        if any(
            key.turn_id == item.id.split(":", 1)[0]
            and key.tool_call_id == item.id.split(":", 1)[1]
            and key.tool_name == item.capability
            for key in replay.pending_approvals
        )
    )
    return TaskSnapshot(
        task_id=task_id,
        state=state,
        sequence_cursor=cursor,
        created_at=created_at,
        updated_at=updated_at,
        artifacts=tuple(artifacts.values()),
        terminal_error_code=terminal_error_code,
        pending_approvals=pending_summaries,
    )
