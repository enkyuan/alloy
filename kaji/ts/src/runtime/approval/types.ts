/** Typed approval decisions and the canonical runtime request context. */
import type { EventCommitter } from "@/events/protocols";
import type { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import type { ToolCall } from "@/providers/base";
import type { ToolExecutionContext } from "@/runtime/context";
import type { ToolRisk } from "@/tools/policy";

export type ApprovalRejectionCode = "rejected" | "timeout" | "cancelled" | "unavailable";

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
  readonly deadlineMs: number;
}

/** @deprecated Use ApprovalRequestContext. */
export type EventApprovalContext = ApprovalRequestContext;
/** @deprecated Use ApprovalRequestContext. */
export type ToolContext = ApprovalRequestContext;

/** @deprecated Implement TypedApprovalHandler directly. */
export interface ApprovalRequest {
  call: ToolCall;
  ctx: ToolContext;
}

export interface TypedApprovalHandler {
  request(call: ToolCall, context: ApprovalRequestContext): Promise<ApprovalDecision>;
}

/** Dedicated marker for the one handler that owns approval-request emission. */
export interface EventBackedApprovalHandler extends TypedApprovalHandler {
  readonly approvalRequestOwner: "handler";
}

/** @deprecated Return ApprovalDecision from a TypedApprovalHandler instead. */
export type LegacyApprovalHandler = (
  name: string,
  args: Record<string, unknown>,
  risk: string | undefined,
) => Promise<boolean>;

let legacyWarningEmitted = false;

function warnLegacyApprovalHandler(): void {
  try {
    console.warn(
      "[kaji] Boolean approval callbacks are deprecated; implement TypedApprovalHandler instead",
    );
  } catch {
    // Diagnostics are observational and must not block the callback.
  }
}

/** Single compatibility boundary for the pre-beta Boolean callback. */
export async function requestLegacyApproval(
  handler: LegacyApprovalHandler,
  call: ToolCall,
  args: Readonly<Record<string, unknown>>,
  risk: ToolRisk,
): Promise<ApprovalDecision> {
  if (!legacyWarningEmitted) {
    legacyWarningEmitted = true;
    warnLegacyApprovalHandler();
  }
  const granted = await handler(call.name, structuredClone(args), risk);
  if (typeof granted !== "boolean") {
    throw new TypeError("Legacy approval callback must return Boolean");
  }
  return granted
    ? { granted: true, code: "approved" }
    : {
        granted: false,
        code: "rejected",
        reason: "Rejected by approval handler",
      };
}

/** Single compatibility adapter for hosts migrating to TypedApprovalHandler. */
export function adaptLegacyApprovalHandler(handler: LegacyApprovalHandler): TypedApprovalHandler {
  return {
    async request(call, context) {
      return requestLegacyApproval(handler, call, context.arguments, context.risk);
    },
  };
}
