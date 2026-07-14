/** Typed approval decisions and the canonical runtime request context. */
import type { EventCommitter } from "@/events/protocols";
import type { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import type { ToolCall } from "@/providers/base";
import type { ToolExecutionContext } from "@/runtime/context";
import type { TimerScheduler } from "@/internal/uuid";
import type { ToolRisk } from "@/tools/policy";

export type ApprovalRejectionCode =
  | "rejected"
  | "timeout"
  | "turn_timeout"
  | "cancelled"
  | "unavailable";

export type ApprovalDeadlineSource = "approval" | "turn";

export type ApprovalDecision =
  | Readonly<{ granted: true; code: "approved"; recorded?: boolean }>
  | Readonly<{
      granted: false;
      code: ApprovalRejectionCode;
      reason: string;
      recorded?: boolean;
    }>;

/**
 * Runtime-owned approval boundary. `committer` is used only to subscribe;
 * `emit` is the canonical runtime write path so projection and turn collection
 * stay coherent.
 */
export interface ApprovalRequestContext {
  readonly execution: ToolExecutionContext;
  readonly toolName: string;
  readonly risk: ToolRisk;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly committer: EventCommitter;
  readonly emit: (event: KajiEvent) => Promise<StoredKajiEvent>;
  readonly deadlineMonotonicMs: number;
  readonly deadlineSource: ApprovalDeadlineSource;
  /** Runtime clock paired with `deadlineMonotonicMs`; custom contexts may omit it. */
  readonly nowMonotonic?: () => number;
  readonly timerScheduler: TimerScheduler;
}

export interface TypedApprovalHandler {
  request(call: ToolCall, context: ApprovalRequestContext): Promise<ApprovalDecision>;
}

/** Dedicated marker for the one handler that owns approval-request emission. */
export interface EventBackedApprovalHandler extends TypedApprovalHandler {
  readonly approvalRequestOwner: "handler";
}
