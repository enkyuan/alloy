/**
 * Tool policy enforcement, mirroring `agentkit.runtime.tools.policies`.
 * Controls which tools may run and which require explicit approval before
 * execution, keyed on tool name and risk classification.
 */
import type { ToolRisk } from "./registry";

export type { ToolRisk };

/** Thrown by `ToolPolicy.enforce` when a tool call is not permitted. */
export class ToolPolicyViolation extends Error {
  constructor(toolName: string) {
    super(`Tool not permitted: ${toolName}`);
    this.name = "ToolPolicyViolation";
  }
}

export interface ToolPolicyOptions {
  /** Explicit allowlist. When undefined, all tools not in `denied` are allowed. */
  allowed?: Set<string>;
  /** Tools that are always blocked, even if in `allowed`. */
  denied?: Set<string>;
  /** Risk levels that require explicit approval before the tool runs. */
  requireApprovalFor?: Set<ToolRisk>;
}

export class ToolPolicy {
  private readonly allowed: Set<string> | undefined;
  private readonly denied: Set<string>;
  readonly requireApprovalFor: Set<ToolRisk>;

  constructor(opts: ToolPolicyOptions = {}) {
    this.allowed = opts.allowed;
    this.denied = opts.denied ?? new Set();
    this.requireApprovalFor = opts.requireApprovalFor ?? new Set();
  }

  /** Returns true when the tool is not denied and (if an allowlist exists) is in it. */
  isAllowed(toolName: string): boolean {
    if (this.denied.has(toolName)) return false;
    if (this.allowed === undefined) return true;
    return this.allowed.has(toolName);
  }

  isAllowedAny(toolNames: Iterable<string>): boolean {
    const names = new Set(toolNames);
    for (const name of names) {
      if (this.denied.has(name)) return false;
    }
    if (this.allowed === undefined) return true;
    for (const name of names) {
      if (this.allowed.has(name)) return true;
    }
    return false;
  }

  /** Throws `ToolPolicyViolation` if the tool is not allowed. */
  enforce(toolName: string): void {
    if (!this.isAllowed(toolName)) throw new ToolPolicyViolation(toolName);
  }

  enforceAny(toolName: string, aliases: Iterable<string> = []): void {
    if (!this.isAllowedAny([toolName, ...aliases])) throw new ToolPolicyViolation(toolName);
  }

  /**
   * Returns true when the tool's effective risk level is in the approval set.
   * `undefined` risk is treated as `"read"` (lowest risk), matching Python behaviour.
   */
  requiresApproval(_toolName: string, risk: ToolRisk | undefined): boolean {
    if (this.requireApprovalFor.size === 0) return false;
    const effectiveRisk: ToolRisk = risk ?? "read";
    return this.requireApprovalFor.has(effectiveRisk);
  }
}
