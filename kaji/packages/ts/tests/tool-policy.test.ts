import { describe, it, expect } from "vitest";
import { ToolPolicy, ToolPolicyViolation } from "@/tools/policy";
import { UnclassifiedToolRiskError } from "@/tools/registry";
import { ToolSchemaValidationError } from "@/tools/validation";

describe("ToolPolicy", () => {
  it("allowlist permits listed tools and blocks others", () => {
    const policy = new ToolPolicy({ allowed: new Set(["search", "calendar"]) });
    expect(policy.isAllowed("search")).toBe(true);
    expect(policy.isAllowed("delete")).toBe(false);
  });

  it("denylist wins over allowlist", () => {
    const policy = new ToolPolicy({ allowed: new Set(["search"]), denied: new Set(["search"]) });
    expect(policy.isAllowed("search")).toBe(false);
  });

  it("enforce throws ToolPolicyViolation for denied tools", () => {
    const policy = new ToolPolicy({ allowed: new Set(["search"]) });
    expect(() => policy.enforce("delete")).toThrow(ToolPolicyViolation);
    expect(() => policy.enforce("delete")).toThrow("not permitted");
  });

  it("requiresApproval returns true when risk is in the approval set", () => {
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive", "admin"]) });
    expect(policy.requiresApproval("delete_all", "destructive")).toBe(true);
    expect(policy.requiresApproval("manage_users", "admin")).toBe(true);
  });

  it("requiresApproval returns false for lower risk or no set configured", () => {
    const withSet = new ToolPolicy({ requireApprovalFor: new Set(["destructive", "admin"]) });
    expect(withSet.requiresApproval("search", "read")).toBe(false);
    expect(() => withSet.requiresApproval("search", undefined)).toThrow(UnclassifiedToolRiskError);

    const noSet = new ToolPolicy();
    expect(noSet.requiresApproval("delete_all", "destructive")).toBe(false);
  });

  it("snapshots caller-owned sets", () => {
    const allowed = new Set(["search"]);
    const denied = new Set(["delete"]);
    const requireApprovalFor = new Set(["write"] as const);
    const policy = new ToolPolicy({ allowed, denied, requireApprovalFor });

    allowed.clear();
    allowed.add("delete");
    denied.clear();
    requireApprovalFor.clear();

    expect(policy.isAllowed("search")).toBe(true);
    expect(policy.isAllowed("delete")).toBe(false);
    expect(policy.requiresApproval("update", "write")).toBe(true);
  });

  it("rejects unknown approval risks during construction", () => {
    expect(
      () =>
        new ToolPolicy({
          requireApprovalFor: new Set(["typo"]) as unknown as Set<"read">,
        }),
    ).toThrowError(
      expect.objectContaining({
        code: "INVALID_TOOL_SCHEMA",
        path: "/risk",
      }),
    );
    expect(
      () =>
        new ToolPolicy({
          requireApprovalFor: new Set(["typo"]) as unknown as Set<"read">,
        }),
    ).toThrow(ToolSchemaValidationError);
  });
});
