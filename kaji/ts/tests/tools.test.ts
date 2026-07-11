import { afterEach, describe, expect, it } from "vitest";
import * as z from "zod";

import { ToolPolicy, listToolSpecs, registerTool, tool, toolSpecFromSchema } from "@/index";
import { TOOL_META, ToolRegistry, clearTools, executeTool } from "@/tools/registry";
import { ToolSchemaValidator } from "@/tools/validation";
import { AgentRuntime } from "@/runtime/runtime";
import { MockProvider } from "@/providers/mock";
import { EventBus } from "@/events/bus";
import { EventType } from "@/events/types";
import { InMemoryEventStore } from "@/events/store";
import { KajiEvent } from "@/events/schemas";

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
        $schema: "https://json-schema.org/draft/2020-12/schema",
        type: "object",
        properties: { city: { type: "string" }, units: { type: "string" } },
        required: ["city"],
      },
    });
  });

  it("preserves complete Zod validation constraints", () => {
    const spec = toolSpecFromSchema(
      "bounded_tags",
      "Validate bounded tags",
      z.strictObject({ tags: z.array(z.string().min(2)).min(1).max(2) }),
    );

    expect(spec.parameters).toMatchObject({
      $schema: "https://json-schema.org/draft/2020-12/schema",
      type: "object",
      required: ["tags"],
      additionalProperties: false,
      properties: {
        tags: {
          type: "array",
          minItems: 1,
          maxItems: 2,
          items: { type: "string", minLength: 2 },
        },
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
    expect(() => registerTool(spec, async () => ({}))).toThrow(/already registered/);
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

  it("registerTool(name, taggedHandler) derives spec from TOOL_META", async () => {
    const handler = tool(
      {
        description: "Ping the service",
        parameters: z.object({ message: z.string() }),
        risk: "read",
      },
      async (_ctx, _args) => ({ pong: true }),
    );

    registerTool("ping", handler);

    const specs = listToolSpecs();
    expect(specs).toHaveLength(1);
    expect(specs[0]).toMatchObject({
      name: "ping",
      description: "Ping the service",
      risk: "read",
    });
    expect(specs[0]?.parameters).toEqual({
      $schema: "https://json-schema.org/draft/2020-12/schema",
      type: "object",
      properties: { message: { type: "string" } },
      required: ["message"],
    });

    const result = await executeTool("u", "ping", { message: "hello" });
    expect(result).toEqual({ pong: true });
  });

  it("registerTool(name, handler) throws when handler has no TOOL_META", () => {
    const bare = async () => ({});
    expect(() => registerTool("bare", bare)).toThrow(/TOOL_META/);
  });
});

describe("ToolRegistry", () => {
  it("adds every registration to the injected compiler environment", async () => {
    const compiler = new ToolSchemaValidator();
    const registry = new ToolRegistry(compiler);

    for (const name of ["one", "two", "three"]) {
      registry.register(
        {
          name,
          description: name,
          parameters: {
            type: "object",
            required: ["value"],
            properties: { value: { type: "string" } },
          },
        },
        async () => ({}),
      );
    }

    for (const name of ["one", "two", "three"]) {
      await expect(compiler.validate(name, { value: 1 })).rejects.toMatchObject({
        code: "INVALID_TOOL_ARGUMENTS",
        path: "/value",
      });
    }
  });

  it("snapshots caller specs before compiling and publishing", async () => {
    const spec = {
      name: "snapshot",
      description: "snapshot",
      parameters: {
        type: "object",
        required: ["value"],
        properties: { value: { type: "string" } },
      },
    };
    const registry = new ToolRegistry();
    registry.register(spec, async (_context, args) => ({ value: args.value }));

    spec.parameters.properties.value.type = "number";

    await expect(registry.execute("u", "snapshot", { value: "stable" })).resolves.toEqual({
      value: "stable",
    });
    await expect(registry.execute("u", "snapshot", { value: 1 })).rejects.toMatchObject({
      code: "INVALID_TOOL_ARGUMENTS",
      path: "/value",
    });
    expect((registry.listSpecs()[0]!.parameters.properties as any).value.type).toBe("string");
  });

  it("publishes deeply immutable specs", async () => {
    const registry = new ToolRegistry();
    registry.register(
      {
        name: "immutable",
        description: "immutable",
        tags: ["stable"],
        parameters: { type: "object", properties: { value: { type: "string" } } },
      },
      async () => ({ ok: true }),
    );
    const listed = registry.listSpecs()[0]!;

    expect(Object.isFrozen(listed)).toBe(true);
    expect(Object.isFrozen(listed.parameters)).toBe(true);
    expect(Object.isFrozen((listed.parameters.properties as any).value)).toBe(true);
    expect(Object.isFrozen(listed.tags)).toBe(true);
    expect(() => {
      (listed.parameters.properties as any).value.type = "number";
    }).toThrow();
    expect(() => (listed.tags as string[]).push("mutated")).toThrow();
    await expect(registry.execute("u", "immutable", { value: "stable" })).resolves.toEqual({
      ok: true,
    });
  });

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

  it("register(name, taggedHandler) derives spec from TOOL_META", async () => {
    const registry = new ToolRegistry();
    const handler = tool(
      {
        description: "Get balance",
        parameters: { type: "object", properties: {} },
        risk: "read",
        tags: ["finance"],
      },
      async (_ctx, _args) => ({ balance: 42 }),
    );

    registry.register("getBalance", handler);

    const specs = registry.listSpecs();
    expect(specs).toHaveLength(1);
    expect(specs[0]).toMatchObject({
      name: "getBalance",
      description: "Get balance",
      risk: "read",
      tags: ["finance"],
    });

    const result = await registry.execute("u", "getBalance", {});
    expect(result).toEqual({ balance: 42 });
  });

  it("register(name, handler) throws when handler has no TOOL_META", () => {
    const registry = new ToolRegistry();
    const bare = async () => ({});
    expect(() => registry.register("bare", bare)).toThrow(/TOOL_META/);
  });

  it("TOOL_META symbol is exported and can be read from tagged handlers", () => {
    const handler = tool({ description: "Test", parameters: {} }, async () => ({}));
    const meta = (handler as unknown as Record<symbol, unknown>)[TOOL_META];
    expect(meta).toBeDefined();
    expect((meta as { description: string }).description).toBe("Test");
  });
});

describe("AgentRuntime with ToolPolicy", () => {
  async function seed(store: InMemoryEventStore, sessionId: string) {
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }));
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "do something",
      }),
    );
  }

  it("emits TOOL_CALL_FAILED when a denied tool is called", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const policy = new ToolPolicy({ denied: new Set(["dangerous_op"]) });
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      bus,
      policy,
      userId: "test-user",
    });

    const s = "s-policy-denied";
    await seed(store, s);
    registerTool({ name: "dangerous_op", description: "d", parameters: {} }, async () => ({
      done: true,
    }));

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    const failed = events.filter((e) => e.type === EventType.TOOL_CALL_FAILED);
    expect(failed.length).toBeGreaterThan(0);
    const failedEvent = failed[0];
    if (failedEvent && "error" in failedEvent) {
      expect(failedEvent.error).toMatch(/not permitted/);
    }
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(false);
  });

  it("emits TOOL_APPROVAL_REJECTED and TOOL_CALL_FAILED for financial-risk tools with no approval handler", async () => {
    // When no approvalHandler is configured, the planner emits TOOL_APPROVAL_REJECTED
    // (for approval-aware consumers) AND TOOL_CALL_FAILED (so replaySession projects
    // the outcome into model history and the loop terminates cleanly).
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["financial"]) });
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      bus,
      policy,
      userId: "test-user",
    });

    const s = "s-policy-approval";
    await seed(store, s);
    registerTool(
      { name: "charge_card", description: "charges a card", parameters: {}, risk: "financial" },
      async () => ({ charged: true }),
    );

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    // Approval-aware consumers see the rejection event.
    expect(events.some((e) => e.type === EventType.TOOL_APPROVAL_REJECTED)).toBe(true);
    // Replay-visible TOOL_CALL_FAILED so the model loop terminates.
    const failed = events.filter((e) => e.type === EventType.TOOL_CALL_FAILED);
    expect(failed.length).toBeGreaterThan(0);
    const failedEvent = failed[0];
    if (failedEvent && "error" in failedEvent) {
      expect(failedEvent.error).toMatch(/approval rejected/i);
    }
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(false);
  });

  it("executes tools normally when no policy is configured", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });

    const s = "s-no-policy";
    await seed(store, s);
    registerTool({ name: "safe_op", description: "safe", parameters: {} }, async () => ({
      ok: true,
    }));

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(true);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(false);
  });
});
