import type { ArtifactRef } from "@/artifacts/types";

export const TaskState = {
  CREATED: "created",
  RUNNING: "running",
  WAITING_FOR_APPROVAL: "waiting_for_approval",
  SUSPENDED: "suspended",
  RECONCILIATION_REQUIRED: "reconciliation_required",
  COMPLETED: "completed",
  FAILED: "failed",
  CANCELLED: "cancelled",
} as const;

export type TaskState = (typeof TaskState)[keyof typeof TaskState];

export interface PendingApprovalSummary {
  readonly id: string;
  readonly capability: string;
  readonly risk: string;
}

export interface PendingApproval extends PendingApprovalSummary {
  readonly arguments: Readonly<Record<string, unknown>>;
}

export interface TaskSnapshot {
  readonly task_id: string;
  readonly state: TaskState;
  readonly sequence_cursor: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly artifacts: readonly ArtifactRef[];
  readonly terminal_error_code?: string;
  readonly pending_approvals: readonly PendingApprovalSummary[];
}
