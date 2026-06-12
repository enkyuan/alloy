import { describe, expect, it } from "vitest";

import { Integration } from "../src/integrations/base";
import { ToolRegistry } from "../src/tools/registry";
import type { ToolHandler, ToolSpec } from "../src/tools/registry";

const dummyHandler: ToolHandler = async (_ctx, _args) => ({ ok: true });
const dummySpec: ToolSpec = { name: "bar", description: "A test tool", parameters: {} };

class FooIntegration extends Integration {
  readonly namespace = "foo";
  tools(): [ToolSpec, ToolHandler][] {
    return [[dummySpec, dummyHandler]];
  }
}

class MultiToolIntegration extends Integration {
  readonly namespace = "svc";
  tools(): [ToolSpec, ToolHandler][] {
    return [
      [{ name: "alpha", description: "alpha", parameters: {} }, dummyHandler],
      [{ name: "beta", description: "beta", parameters: {} }, dummyHandler],
    ];
  }
}

describe("Integration", () => {
  it("namespace prefixes tool names", () => {
    const registry = new ToolRegistry();
    new FooIntegration().register(registry);
    const names = registry.listSpecs({ enabledOnly: false }).map((s) => s.name);
    expect(names).toEqual(["foo.bar"]);
  });

  it("multiple tools all prefixed", () => {
    const registry = new ToolRegistry();
    new MultiToolIntegration().register(registry);
    const names = registry
      .listSpecs({ enabledOnly: false })
      .map((s) => s.name)
      .sort();
    expect(names).toEqual(["svc.alpha", "svc.beta"]);
  });

  it("concrete implementation with namespace and tools works correctly", () => {
    // TypeScript enforces abstract members at compile time.
    // This test verifies a correct concrete class instantiates and registers.
    const registry = new ToolRegistry();
    new FooIntegration().register(registry);
    expect(registry.listSpecs({ enabledOnly: false })).toHaveLength(1);
  });

  it("register() delegates to the ToolRegistry with prefixed specs", () => {
    const registry = new ToolRegistry();
    new FooIntegration().register(registry);
    const specs = registry.listSpecs({ enabledOnly: false });
    expect(specs).toHaveLength(1);
    expect(specs[0]!.name).toBe("foo.bar");
    expect(specs[0]!.description).toBe("A test tool");
  });
});
