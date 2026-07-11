export type {
  ApprovalDecision,
  ApprovalRequest,
  ApprovalRejectionCode,
  ApprovalRequestContext,
  EventApprovalContext,
  EventBackedApprovalHandler,
  LegacyApprovalHandler,
  ToolContext,
  TypedApprovalHandler,
} from "@/runtime/approval/types";
export { adaptLegacyApprovalHandler, requestLegacyApproval } from "@/runtime/approval/types";
export { EventApprovalHandler } from "@/runtime/approval/handler";
export type { EventApprovalHandlerOptions } from "@/runtime/approval/handler";
export { AutoApprovalHandler, type AutoApprovalPolicy } from "@/runtime/approval/auto";
