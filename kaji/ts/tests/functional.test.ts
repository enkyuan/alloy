import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  AgentBuilder,
  BoundTool,
  EventType,
  functionTool,
  InMemoryEventStore,
  ToolRegistry,
} from "@/index";
import { MockProvider } from "@/testing";

describe("functionTool", () => {
  it("produces a BoundTool with the handler name", () => {
    async function getWeather({ city }: { city: string }): Promise<unknown> {
      return { city, tempF: 68 };
    }
    const bound = functionTool(
      { description: "weather", parameters: z.object({ city: z.string() }) },
      getWeather,
    );
    expect(bound).toBeInstanceOf(BoundTool);
    expect(bound.spec.name).toBe("getWeather");
    expect(bound.spec.description).toBe("weather");
  });

  it("converts Zod schema to JSON Schema", () => {
    const bound = functionTool(
      {
        name: "search",
        description: "search",
        parameters: z.object({ query: z.string(), limit: z.number().optional() }),
      },
      async () => [],
    );
    const schema = bound.spec.parameters;
    expect(schema.type).toBe("object");
    expect((schema as any).properties).toHaveProperty("query");
    expect((schema as any).required).toContain("query");
  });

  it("registers with namespace prefix", () => {
    const bound = functionTool(
      { name: "ping", description: "ping", parameters: z.object({}) },
      async () => "pong",
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const specs = registry.listSpecs({ enabledOnly: false });
    expect(specs).toHaveLength(1);
    expect(specs[0]!.name).toBe("fn_ping");
    expect(specs[0]!.catalogName).toBe("fn.ping");
  });

  it("executes end-to-end through AgentBuilder().tool()", async () => {
    const store = new InMemoryEventStore();
    const echo = functionTool(
      {
        name: "echo",
        description: "echo",
        parameters: z.object({ message: z.string() }),
      },
      async ({ message }) => ({ echoed: message }),
    );
    const runtime = new AgentBuilder().provider(new MockProvider()).tool(echo).build({ store });
    await runtime.send("s1", "hello");
    const events = await runtime.history("s1");
    const types = events.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
  });

  it("forwards parsed args directly (no ctx parameter)", async () => {
    const bound = functionTool(
      {
        name: "add",
        description: "add",
        parameters: z.object({ x: z.number(), y: z.number() }),
      },
      async ({ x, y }) => ({ sum: x + y }),
    );
    const result = await bound.handler({ userId: "_" } as any, { x: 2, y: 3 });
    expect(result).toEqual({ sum: 5 });
  });
});
