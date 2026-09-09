import { validateArtifactRef, type ArtifactRef } from "@/artifacts/types";
import { EventType } from "@/events/types";
import type { StoredKajiEvent } from "@/events/schemas";
import { approvalKey, replaySession } from "@/sessions/replay";

import {
  TaskState,
  type PendingApproval,
  type PendingApprovalSummary,
  type TaskSnapshot,
} from "./types";

const terminal = new Set<TaskState>([TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED]);
const activity = new Set<string>([
  EventType.SESSION_CREATED,
  EventType.USER_MESSAGE,
  EventType.AGENT_REASONING_STARTED,
  EventType.TOOL_CALL_REQUESTED,
  EventType.TOOL_CALL_STARTED,
  EventType.TOOL_CALL_COMPLETED,
]);

export class TaskProjectionError extends Error {}
export class InvalidTaskTransitionError extends TaskProjectionError {}

export function approvalId(event: { turn_id: string; tool_call_id: string }): string {
  return `${event.turn_id}:${event.tool_call_id}`;
}

function timestamp(value: number): string {
  return new Date(value * 1000).toISOString();
}

function transition(current: TaskState, target: TaskState): TaskState {
  if (terminal.has(current))
    throw new InvalidTaskTransitionError(
      `cannot transition terminal task from ${current} to ${target}`,
    );
  if (
    target === TaskState.SUSPENDED &&
    !(
      [
        TaskState.RUNNING,
        TaskState.WAITING_FOR_APPROVAL,
        TaskState.RECONCILIATION_REQUIRED,
      ] as TaskState[]
    ).includes(current)
  ) {
    throw new InvalidTaskTransitionError(`cannot suspend task from ${current}`);
  }
  if (
    target === TaskState.RUNNING &&
    !(
      [
        TaskState.CREATED,
        TaskState.SUSPENDED,
        TaskState.WAITING_FOR_APPROVAL,
        TaskState.RECONCILIATION_REQUIRED,
      ] as TaskState[]
    ).includes(current)
  ) {
    throw new InvalidTaskTransitionError(`cannot resume task from ${current}`);
  }
  return target;
}

export function projectTask(taskId: string, input: readonly StoredKajiEvent[]): TaskSnapshot {
  let state: TaskState | undefined;
  let createdAt: string | undefined;
  let updatedAt: string | undefined;
  let cursor = 0;
  let terminalErrorCode: string | undefined;
  let previousSequence = 0;
  const artifacts = new Map<string, ArtifactRef>();
  const pending = new Map<string, PendingApproval>();

  for (const event of input) {
    if (event.sequence <= previousSequence)
      throw new TaskProjectionError("task events must be in ascending sequence order");
    previousSequence = event.sequence;
    const eventTaskId = "task_id" in event ? event.task_id : undefined;
    if (event.type === EventType.TASK_CREATED) {
      if (eventTaskId !== taskId) continue;
      if (state) throw new TaskProjectionError(`duplicate task.created for ${taskId}`);
      state = TaskState.CREATED;
      createdAt = timestamp(event.timestamp);
    } else if (!state) {
      continue;
    } else if (eventTaskId !== undefined && eventTaskId !== taskId) {
      continue;
    } else if (event.type === EventType.TASK_SUSPENDED) {
      state = transition(state, TaskState.SUSPENDED);
    } else if (event.type === EventType.TASK_RESUMED) {
      state = transition(state, TaskState.RUNNING);
    } else if (event.type === EventType.TASK_COMPLETED) {
      state = transition(state, TaskState.COMPLETED);
    } else if (event.type === EventType.TASK_FAILED) {
      state = transition(state, TaskState.FAILED);
      terminalErrorCode = event.error_code;
    } else if (event.type === EventType.TASK_CANCELLED) {
      state = transition(state, TaskState.CANCELLED);
    } else if (event.type === EventType.TOOL_APPROVAL_REQUESTED) {
      const id = approvalId(event);
      pending.set(id, {
        id,
        capability: event.tool_name,
        risk: event.risk,
        arguments: event.tool_args,
      });
      if (!terminal.has(state) && state !== TaskState.RECONCILIATION_REQUIRED)
        state = TaskState.WAITING_FOR_APPROVAL;
    } else if (
      event.type === EventType.TOOL_APPROVAL_APPROVED ||
      event.type === EventType.TOOL_APPROVAL_REJECTED
    ) {
      pending.delete(approvalId(event));
      if (state === TaskState.WAITING_FOR_APPROVAL) state = TaskState.RUNNING;
    } else if (event.type === EventType.TOOL_CALL_FAILED && event.outcome === "unknown") {
      if (!terminal.has(state)) state = TaskState.RECONCILIATION_REQUIRED;
    } else if (event.type === EventType.AGENT_TURN_FAILED) {
      if (!terminal.has(state) && state !== TaskState.RECONCILIATION_REQUIRED) {
        state = TaskState.FAILED;
        terminalErrorCode = event.error_code;
      }
    } else if (event.type === EventType.CANCELLATION_COMPLETED) {
      if (!terminal.has(state) && state !== TaskState.RECONCILIATION_REQUIRED)
        state = TaskState.CANCELLED;
    } else if (activity.has(event.type) && state === TaskState.CREATED) {
      state = TaskState.RUNNING;
    }

    if (event.type === EventType.ARTIFACT_EMITTED) {
      const artifact = validateArtifactRef(event.artifact);
      const existing = artifacts.get(artifact.id);
      if (existing && JSON.stringify(existing) !== JSON.stringify(artifact))
        throw new TaskProjectionError(`conflicting artifact id ${artifact.id}`);
      artifacts.set(artifact.id, artifact);
    }
    cursor = event.sequence;
    updatedAt = timestamp(event.timestamp);
  }

  if (!state || !createdAt || !updatedAt)
    throw new TaskProjectionError(`task ${taskId} was not created in this journal`);
  const replay = replaySession(input);
  const pendingApprovals: PendingApprovalSummary[] = [...pending.values()]
    .filter((item) => {
      const [turnId, toolCallId] = item.id.split(":", 2);
      return replay.pendingApprovals.has(approvalKey(turnId!, toolCallId!, item.capability));
    })
    .map(({ id, capability, risk }) => ({ id, capability, risk }));
  return Object.freeze({
    task_id: taskId,
    state,
    sequence_cursor: cursor,
    created_at: createdAt,
    updated_at: updatedAt,
    artifacts: Object.freeze([...artifacts.values()]),
    ...(terminalErrorCode ? { terminal_error_code: terminalErrorCode } : {}),
    pending_approvals: Object.freeze(pendingApprovals),
  });
}
