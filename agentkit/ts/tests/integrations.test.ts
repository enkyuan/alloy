import { describe, expect, it } from "vitest";
import { z } from "zod";

import { Integration, tool } from "../src/integrations/base";
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
  it("namespace creates provider-safe tool names and preserves catalog names", () => {
    const registry = new ToolRegistry();
    new FooIntegration().register(registry);
    const specs = registry.listSpecs({ enabledOnly: false });
    expect(specs.map((s) => s.name)).toEqual(["foo_bar"]);
    expect(specs.map((s) => s.catalogName)).toEqual(["foo.bar"]);
  });

  it("multiple tools all prefixed", () => {
    const registry = new ToolRegistry();
    new MultiToolIntegration().register(registry);
    const names = registry
      .listSpecs({ enabledOnly: false })
      .map((s) => s.name)
      .sort();
    expect(names).toEqual(["svc_alpha", "svc_beta"]);
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
    expect(specs[0]!.name).toBe("foo_bar");
    expect(specs[0]!.catalogName).toBe("foo.bar");
    expect(specs[0]!.description).toBe("A test tool");
  });

  // --- tool() decorator tests ---

  it("tool() marks handler with metadata", () => {
    const handler = tool(
      {
        description: "Make a payment",
        parameters: { amount: { type: "number" } },
        risk: "financial",
      },
      async (_ctx, _args) => ({ ok: true }),
    );
    // The returned function must be callable and carry the marker.
    expect(typeof handler).toBe("function");
    // We verify metadata is present by using it in a class (see next test).
    // Here we just assert the returned value is a function.
    expect(handler).toBeDefined();
  });

  it("Integration.tools() auto-discovers tool() methods", () => {
    class PayIntegration extends Integration {
      readonly namespace = "pay";

      readonly makePayment = tool(
        {
          description: "Make a payment",
          parameters: z.object({ amount: z.number() }),
          risk: "financial",
        },
        async (_ctx, _args) => ({ paid: true }),
      );
    }

    const integration = new PayIntegration();
    const pairs = integration.tools();
    expect(pairs).toHaveLength(1);
    const [spec, handler] = pairs[0]!;
    expect(spec.name).toBe("makePayment");
    expect(spec.description).toBe("Make a payment");
    expect(spec.parameters).toEqual({
      type: "object",
      properties: { amount: { type: "number" } },
      required: ["amount"],
    });
    expect(spec.risk).toBe("financial");
    expect(typeof handler).toBe("function");
  });

  it("manual tools() override still works", () => {
    const customSpec: ToolSpec = { name: "custom_op", description: "Custom", parameters: {} };

    class ManualIntegration extends Integration {
      readonly namespace = "manual";
      tools(): [ToolSpec, ToolHandler][] {
        return [[customSpec, dummyHandler]];
      }
    }

    const registry = new ToolRegistry();
    new ManualIntegration().register(registry);
    const names = registry.listSpecs({ enabledOnly: false }).map((s) => s.name);
    expect(names).toEqual(["manual_custom_op"]);
  });
});
