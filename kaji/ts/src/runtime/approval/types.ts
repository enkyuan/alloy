/**
 * Core types for the approval handler infrastructure.
 * `TypedApprovalHandler` is the structured alternative to the legacy
 * `ApprovalHandler` function type.
 */
import type { ToolCall } from "@/providers/base";

export interface ToolContext {
  sessionId: string;
  risk?: string;
  turnId?: string;
}

/** Correlation context required by event-backed approval handlers. */
export interface EventApprovalContext extends ToolContext {
  turnId: string;
}

export interface ApprovalDecision {
  granted: boolean;
  reason?: string;
}

export interface ApprovalRequest {
  call: ToolCall;
  ctx: ToolContext;
}

export interface TypedApprovalHandler {
  readonly emitsApprovalRequest?: false;
  request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision>;
}

export interface EventBackedApprovalHandler {
  readonly emitsApprovalRequest: true;
  request(call: ToolCall, ctx: EventApprovalContext): Promise<ApprovalDecision>;
}
