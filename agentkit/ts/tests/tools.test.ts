import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import {
  ToolRegistry,
  clearTools,
  executeTool,
  listToolSpecs,
  registerTool,
  toolSpecFromSchema,
} from "../src/index";

afterEach(() => {
  clearTools();
});

describe("tool registry", () => {
  it("builds a spec from a Zod schema in the LLM tool shape", () => {
    const spec = toolSpecFromSchema(
      "get_weather",
      "Look up weather",
      z.object({ city: z.string(), units: z.string().optional() }),
    );

    expect(spec).toEqual({
      name: "get_weather",
      description: "Look up weather",
      parameters: {
        type: "object",
        properties: { city: { type: "string" }, units: { type: "string" } },
        required: ["city"],
      },
    });
  });

  it("registers and executes a tool with a context", async () => {
    const spec = toolSpecFromSchema(
      "get_weather",
      "Look up weather",
      z.object({ city: z.string() }),
    );
    registerTool(spec, async (ctx, args) => ({
      user: ctx.userId,
      city: args.city,
      tempF: 68,
    }));

    expect(listToolSpecs()).toHaveLength(1);

    const result = await executeTool("user-1", "get_weather", {
      city: "Seattle",
    });
    expect(result).toEqual({ user: "user-1", city: "Seattle", tempF: 68 });
  });

  it("rejects a duplicate registration", () => {
    const spec = toolSpecFromSchema("dup", "d", z.object({}));
    registerTool(spec, async () => ({}));
    expect(() => registerTool(spec, async () => ({}))).toThrow(
      /already registered/,
    );
  });

  it("throws when executing an unknown tool", async () => {
    await expect(executeTool("u", "nope", {})).rejects.toThrow(/Unknown tool/);
  });

  it("passes an injected db handle through the context", async () => {
    const db = { marker: true };
    registerTool(toolSpecFromSchema("needs_db", "d", z.object({})), async (ctx) => ({
      sawDb: ctx.db === db,
    }));
    const result = await executeTool("u", "needs_db", {}, db);
    expect(result).toEqual({ sawDb: true });
  });

  it("listToolSpecs excludes disabled specs by default", () => {
    registerTool({ name: "on", description: "d", parameters: {} }, async () => ({}));
    registerTool(
      { name: "off", description: "d", parameters: {}, enabled: false },
      async () => ({}),
    );
    expect(listToolSpecs().map((s) => s.name)).toEqual(["on"]);
  });

  it("listToolSpecs with enabledOnly:false returns all specs", () => {
    registerTool({ name: "on", description: "d", parameters: {} }, async () => ({}));
    registerTool(
      { name: "off", description: "d", parameters: {}, enabled: false },
      async () => ({}),
    );
    expect(listToolSpecs({ enabledOnly: false })).toHaveLength(2);
  });

  it("listToolSpecs filters by tag", () => {
    registerTool(
      { name: "a", description: "d", parameters: {}, tags: ["payments"] },
      async () => ({}),
    );
    registerTool({ name: "b", description: "d", parameters: {}, tags: ["crm"] }, async () => ({}));
    expect(listToolSpecs({ tags: ["payments"] }).map((s) => s.name)).toEqual(["a"]);
  });

  it("listToolSpecs with empty tags array is treated as no tag filter", () => {
    registerTool(
      { name: "a", description: "d", parameters: {}, tags: ["payments"] },
      async () => ({}),
    );
    // empty array = no tag constraint applied, same as omitting tags
    expect(listToolSpecs({ tags: [] })).toHaveLength(1);
  });
});

describe("ToolRegistry", () => {
  it("register and execute round-trip", async () => {
    const registry = new ToolRegistry();
    registry.register({ name: "ping", description: "d", parameters: {} }, async () => ({
      pong: true,
    }));
    const result = await registry.execute("u", "ping", {});
    expect(result).toEqual({ pong: true });
  });

  it("duplicate registration throws", () => {
    const registry = new ToolRegistry();
    registry.register({ name: "dup", description: "d", parameters: {} }, async () => ({}));
    expect(() =>
      registry.register({ name: "dup", description: "d", parameters: {} }, async () => ({})),
    ).toThrow(/already registered/);
  });

  it("execute throws for unknown tool", async () => {
    const registry = new ToolRegistry();
    await expect(registry.execute("u", "ghost", {})).rejects.toThrow(/Unknown tool/);
  });

  it("listSpecs excludes disabled by default", () => {
    const registry = new ToolRegistry();
    registry.register({ name: "on", description: "d", parameters: {} }, async () => ({}));
    registry.register(
      { name: "off", description: "d", parameters: {}, enabled: false },
      async () => ({}),
    );
    expect(registry.listSpecs().map((s) => s.name)).toEqual(["on"]);
  });

  it("listSpecs with enabledOnly:false returns all", () => {
    const registry = new ToolRegistry();
    registry.register({ name: "on", description: "d", parameters: {} }, async () => ({}));
    registry.register(
      { name: "off", description: "d", parameters: {}, enabled: false },
      async () => ({}),
    );
    expect(registry.listSpecs({ enabledOnly: false })).toHaveLength(2);
  });

  it("listSpecs filters by tag", () => {
    const registry = new ToolRegistry();
    registry.register(
      { name: "a", description: "d", parameters: {}, tags: ["payments"] },
      async () => ({}),
    );
    registry.register({ name: "b", description: "d", parameters: {} }, async () => ({}));
    expect(registry.listSpecs({ tags: ["payments"] }).map((s) => s.name)).toEqual(["a"]);
  });

  it("two registries are isolated", () => {
    const r1 = new ToolRegistry();
    const r2 = new ToolRegistry();
    r1.register({ name: "x", description: "d", parameters: {} }, async () => ({}));
    expect(r2.listSpecs()).toHaveLength(0);
  });
});
