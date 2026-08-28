/**
 * Tool policy enforcement, mirroring `kaji.runtime.tools.policies`.
 * Controls which tools may run and which require explicit approval before
 * execution, keyed on tool name and risk classification.
 */
import { UnclassifiedToolRiskError, type ToolRisk } from "@/tools/registry";
import { ToolSchemaValidationError } from "@/tools/validation";

export type { ToolRisk };

/** Ordered from least to most sensitive. Used for threshold comparisons. */
const RISK_LEVELS = ["read", "write", "external_effect", "destructive", "admin"] as const;
const RISK_RANK = new Map<ToolRisk, number>(RISK_LEVELS.map((risk, rank) => [risk, rank]));

/** Thrown by `ToolPolicy.enforce` when a tool call is not permitted. */
export class ToolPolicyViolation extends Error {
  constructor(toolName: string) {
    super(`Tool not permitted: ${toolName}`);
    this.name = "ToolPolicyViolation";
  }
}

export interface ToolPolicyOptions {
  /** Explicit allowlist. When undefined, all tools not in `denied` are allowed. */
  allowed?: ReadonlySet<string>;
  /** Tools that are always blocked, even if in `allowed`. */
  denied?: ReadonlySet<string>;
  /** Risk levels that require explicit approval before the tool runs. */
  requireApprovalFor?: ReadonlySet<ToolRisk>;
}

export class ToolPolicy {
  private readonly allowed: Set<string> | undefined;
  private readonly denied: Set<string>;
  readonly requireApprovalFor: ReadonlySet<ToolRisk>;

  constructor(opts: ToolPolicyOptions = {}) {
    const requireApprovalFor = new Set(opts.requireApprovalFor ?? []);
    for (const risk of requireApprovalFor) {
      if (!RISK_RANK.has(risk)) throw ToolSchemaValidationError.invalidRisk("ToolPolicy");
    }
    this.allowed = opts.allowed === undefined ? undefined : new Set(opts.allowed);
    this.denied = new Set(opts.denied ?? []);
    this.requireApprovalFor = requireApprovalFor;
  }

  /** Returns true when the tool is not denied and (if an allowlist exists) is in it. */
  isAllowed(toolName: string): boolean {
    if (this.denied.has(toolName)) return false;
    if (this.allowed === undefined) return true;
    return this.allowed.has(toolName);
  }

  isAllowedAny(toolNames: Iterable<string>): boolean {
    let anyAllowed = false;
    for (const name of toolNames) {
      if (this.denied.has(name)) return false;
      if (this.allowed === undefined || this.allowed.has(name)) anyAllowed = true;
    }
    return anyAllowed || this.allowed === undefined;
  }

  /** Throws `ToolPolicyViolation` if the tool is not allowed. */
  enforce(toolName: string): void {
    if (!this.isAllowed(toolName)) throw new ToolPolicyViolation(toolName);
  }

  enforceAny(toolName: string, aliases: Iterable<string> = []): void {
    if (!this.isAllowedAny([toolName, ...aliases])) throw new ToolPolicyViolation(toolName);
  }

  /**
   * Returns true when the tool's effective risk level is at or above the
   * minimum rank in `requireApprovalFor`. So `requireApprovalFor: {"destructive"}`
   * also catches `"admin"`. Enabled tools must carry a known risk; missing
   * and unknown classifications fail instead of defaulting to `read`.
   */
  requiresApproval(_toolName: string, risk: ToolRisk | undefined): boolean {
    if (risk === undefined) throw new UnclassifiedToolRiskError(_toolName);
    const rank = RISK_RANK.get(risk);
    if (rank === undefined) throw ToolSchemaValidationError.invalidRisk(_toolName);
    if (this.requireApprovalFor.size === 0) return false;
    let floor = Infinity;
    for (const r of this.requireApprovalFor) {
      const approvalRank = RISK_RANK.get(r);
      if (approvalRank !== undefined && approvalRank < floor) floor = approvalRank;
    }
    if (floor === Infinity) return this.requireApprovalFor.has(risk);
    return rank >= floor;
  }
}
