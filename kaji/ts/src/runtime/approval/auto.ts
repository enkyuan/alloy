/**
 * Policy-driven approval handler that resolves decisions synchronously
 * without any I/O. Useful for testing, sandboxed environments, or as a
 * safe default that denies everything not explicitly listed.
 */
import type { ToolCall } from "@/providers/base";
import type { TypedApprovalHandler, ToolContext, ApprovalDecision } from "@/runtime/approval/types";

export interface AutoApprovalPolicy {
  /** Tool names to always allow, regardless of `allowAll`. */
  allow: string[];
  /** Tool names to always deny (checked before `allow`). */
  deny: string[];
  /** When `true`, allow any tool that is not in `deny`. Defaults to `false`. */
  allowAll?: boolean;
}

export class AutoApprovalHandler implements TypedApprovalHandler {
  constructor(private readonly policy: AutoApprovalPolicy) {}

  async request(call: ToolCall, _ctx: ToolContext): Promise<ApprovalDecision> {
    const name = call.name;

    if (this.policy.deny.includes(name)) {
      return { granted: false, reason: `Tool "${name}" is in the deny list` };
    }

    if (this.policy.allow.includes(name)) {
      return { granted: true };
    }

    if (this.policy.allowAll === true) {
      return { granted: true };
    }

    return { granted: false, reason: `Tool "${name}" is not in the allow list` };
  }
}
