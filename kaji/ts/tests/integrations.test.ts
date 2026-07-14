import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import { Integration, tool } from "@/integrations/base";
import { ToolRegistry } from "@/tools/registry";
import type { ToolHandler, ToolSpec } from "@/tools/registry";

const dummyHandler: ToolHandler = async (_ctx, _args) => ({ ok: true });
const dummySpec: ToolSpec = {
  name: "bar",
  description: "A test tool",
  parameters: {},
  risk: "read",
};

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
      [{ name: "alpha", description: "alpha", parameters: {}, risk: "read" }, dummyHandler],
      [{ name: "beta", description: "beta", parameters: {}, risk: "read" }, dummyHandler],
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
        risk: "destructive",
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
          risk: "destructive",
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
      $schema: "https://json-schema.org/draft/2020-12/schema",
      type: "object",
      properties: { amount: { type: "number" } },
      required: ["amount"],
    });
    expect(spec.risk).toBe("destructive");
    expect(typeof handler).toBe("function");
  });

  it("validates Zod metadata with byte-equivalent isolated arguments", async () => {
    let transformCalls = 0;
    const original = { amount: "42", label: "lowercase" };
    const implementation = vi.fn(async (args) => ({ args }));
    const handler = tool(
      {
        description: "Validate only",
        risk: "read",
        parameters: z.object({
          amount: z.coerce.number(),
          label: z.string().transform((value) => {
            transformCalls += 1;
            return value.toUpperCase();
          }),
        }),
      },
      implementation,
    );
    const context = {
      principalId: "user-1",
      sessionId: "direct-session",
      turnId: "direct-turn",
      requestId: "direct-request",
      traceId: "direct-trace",
      toolCallId: "direct-call",
      idempotencyKey: "direct-session:direct-call",
      signal: new AbortController().signal,
      metadata: {},
    };

    await expect(handler(original, context)).resolves.toEqual({ args: original });
    expect(implementation).toHaveBeenCalledWith(original, context);
    expect(implementation.mock.calls[0]![0]).not.toBe(original);
    expect(transformCalls).toBe(1);

    const registry = new ToolRegistry();
    registry.register("validate", handler);
    await expect(registry.execute("validate", original, context)).resolves.toEqual({
      args: original,
    });
    expect(transformCalls).toBe(2);
    expect(implementation.mock.calls[1]![0]).not.toBe(original);
  });

  it("manual tools() override still works", () => {
    const customSpec: ToolSpec = {
      name: "custom_op",
      description: "Custom",
      parameters: {},
      risk: "read",
    };

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
