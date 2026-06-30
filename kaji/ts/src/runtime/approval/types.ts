/**
 * Core types for the approval handler infrastructure.
 * `TypedApprovalHandler` is the structured alternative to the legacy
 * `ApprovalHandler` function type.
 */
import type { ToolCall } from "../../providers/base";

export interface ToolContext {
  sessionId: string;
  risk?: string;
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
  readonly emitsApprovalRequest?: boolean;
  request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision>;
}
