import { describe, it, expect } from "vitest";
import { ToolPolicy, ToolPolicyViolation } from "@/tools/policy";

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
    expect(withSet.requiresApproval("search", undefined)).toBe(false);

    const noSet = new ToolPolicy();
    expect(noSet.requiresApproval("delete_all", "destructive")).toBe(false);
  });
});
