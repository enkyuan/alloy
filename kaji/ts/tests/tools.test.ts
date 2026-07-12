import { afterEach, describe, expect, it, vi } from "vitest";
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
import type { ToolExecutionContext } from "@/runtime/context";

function executionContext(overrides: Partial<ToolExecutionContext> = {}): ToolExecutionContext {
  return {
    principalId: "principal",
    sessionId: "session",
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: "call",
    idempotencyKey: "session:call",
    signal: new AbortController().signal,
    metadata: {},
    ...overrides,
  };
}

afterEach(() => {
  clearTools();
});

describe("tool registry", () => {
  it("builds a spec from a Zod schema in the LLM tool shape", () => {
    const spec = toolSpecFromSchema(
      "get_weather",
      "Look up weather",
      z.object({ city: z.string(), units: z.string().optional() }),
      "read",
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
      risk: "read",
    });
  });

  it("preserves complete Zod validation constraints", () => {
    const spec = toolSpecFromSchema(
      "bounded_tags",
      "Validate bounded tags",
      z.strictObject({ tags: z.array(z.string().min(2)).min(1).max(2) }),
      "read",
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
      "read",
    );
    registerTool(spec, async (args, context) => ({
      user: context.principalId,
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
    const spec = toolSpecFromSchema("dup", "d", z.object({}), "read");
    registerTool(spec, async () => ({}));
    expect(() => registerTool(spec, async () => ({}))).toThrow(/already registered/);
  });

  it("throws when executing an unknown tool", async () => {
    await expect(executeTool("u", "nope", {})).rejects.toThrow(/Unknown tool/);
  });

  it("passes an injected db handle through the context", async () => {
    const db = { marker: true };
    registerTool(
      toolSpecFromSchema("needs_db", "d", z.object({}), "read"),
      async (_args, context) => ({
        sawDb: context.db === db,
      }),
    );
    const result = await executeTool("u", "needs_db", {}, db);
    expect(result).toEqual({ sawDb: true });
  });

  it("listToolSpecs excludes disabled specs by default", () => {
    registerTool({ name: "on", description: "d", parameters: {}, risk: "read" }, async () => ({}));
    registerTool(
      { name: "off", description: "d", parameters: {}, enabled: false, risk: "read" },
      async () => ({}),
    );
    expect(listToolSpecs().map((s) => s.name)).toEqual(["on"]);
  });

  it("listToolSpecs with enabledOnly:false returns all specs", () => {
    registerTool({ name: "on", description: "d", parameters: {}, risk: "read" }, async () => ({}));
    registerTool(
      { name: "off", description: "d", parameters: {}, enabled: false, risk: "read" },
      async () => ({}),
    );
    expect(listToolSpecs({ enabledOnly: false })).toHaveLength(2);
  });

  it("listToolSpecs filters by tag", () => {
    registerTool(
      { name: "a", description: "d", parameters: {}, tags: ["payments"], risk: "read" },
      async () => ({}),
    );
    registerTool(
      { name: "b", description: "d", parameters: {}, tags: ["crm"], risk: "read" },
      async () => ({}),
    );
    expect(listToolSpecs({ tags: ["payments"] }).map((s) => s.name)).toEqual(["a"]);
  });

  it("listToolSpecs with empty tags array is treated as no tag filter", () => {
    registerTool(
      { name: "a", description: "d", parameters: {}, tags: ["payments"], risk: "read" },
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
  it("validates, normalizes, detaches, and deeply freezes canonical context", async () => {
    const metadata = { tenant: { id: "stable" }, roles: ["reader"] };
    let captured: ToolExecutionContext | undefined;
    const registry = new ToolRegistry().register(
      { name: "capture_context", description: "capture", parameters: {}, risk: "read" },
      async (_args, context) => {
        captured = context;
        return { principalId: context.principalId };
      },
    );

    const pending = registry.execute(
      "capture_context",
      {},
      executionContext({ principalId: "  principal  ", metadata }),
    );
    metadata.tenant.id = "mutated";
    metadata.roles.push("admin");

    await expect(pending).resolves.toEqual({ principalId: "principal" });
    expect(captured?.metadata).toEqual({ tenant: { id: "stable" }, roles: ["reader"] });
    expect(Object.isFrozen(captured?.metadata)).toBe(true);
    expect(Object.isFrozen(captured?.metadata.tenant)).toBe(true);
    expect(Object.isFrozen(captured?.metadata.roles)).toBe(true);
  });

  it("rejects malformed canonical context before invoking a handler", async () => {
    const handler = vi.fn().mockResolvedValue({ ok: true });
    const registry = new ToolRegistry().register(
      { name: "validated_context", description: "validate", parameters: {}, risk: "read" },
      handler,
    );
    const invalidContexts: ToolExecutionContext[] = [
      executionContext({ principalId: " " }),
      executionContext({ sessionId: " " }),
      executionContext({ turnId: " " }),
      executionContext({ requestId: " " }),
      executionContext({ traceId: " " }),
      executionContext({ toolCallId: " " }),
      executionContext({ idempotencyKey: "wrong" }),
      executionContext({ deadlineMonotonicMs: Number.NaN }),
      executionContext({ deadlineMonotonicMs: -1 }),
      executionContext({ signal: { aborted: false } as AbortSignal }),
    ];

    for (const context of invalidContexts) {
      await expect(registry.execute("validated_context", {}, context)).rejects.toThrow();
    }
    expect(handler).not.toHaveBeenCalled();
  });

  it("dispatches compatibility overloads by exact arity and shape", async () => {
    const registry = new ToolRegistry().register(
      { name: "shape", description: "shape", parameters: {}, risk: "read" },
      async () => ({ ok: true }),
    );
    const untypedExecute = registry.execute.bind(registry) as (
      ...args: unknown[]
    ) => Promise<unknown>;

    await expect(untypedExecute("shape", {}, executionContext())).resolves.toEqual({ ok: true });
    await expect(untypedExecute("principal", "shape", {})).resolves.toEqual({ ok: true });
    await expect(untypedExecute("shape", {}, executionContext(), undefined)).rejects.toThrow(
      TypeError,
    );
    await expect(untypedExecute("principal", "shape", executionContext())).rejects.toThrow(
      TypeError,
    );
    await expect(untypedExecute("shape", {}, { principalId: "partial" })).rejects.toThrow(
      TypeError,
    );
    await expect(untypedExecute("shape", {})).rejects.toThrow(TypeError);
  });

  it("never treats partial context-shaped arguments as legacy tool args", async () => {
    const handler = vi.fn().mockResolvedValue({ ok: true });
    const registry = new ToolRegistry().register(
      { name: "bad-args", description: "bad args", parameters: {}, risk: "read" },
      handler,
    );
    const untypedExecute = registry.execute.bind(registry) as (
      ...args: unknown[]
    ) => Promise<unknown>;
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      untypedExecute("intended-tool", "bad-args", { requestId: "request" }),
    ).rejects.toThrow(TypeError);
    await expect(
      untypedExecute("intended-tool", "bad-args", {
        principalId: "principal",
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow(TypeError);

    expect(warning).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
    warning.mockRestore();
  });

  it("rejects non-JSON metadata at the canonical registry boundary", async () => {
    const handler = vi.fn().mockResolvedValue({ ok: true });
    const registry = new ToolRegistry().register(
      { name: "metadata", description: "metadata", parameters: {}, risk: "read" },
      handler,
    );

    for (const value of [new Map(), new Set(), new Date(), new Uint8Array([1])]) {
      await expect(
        registry.execute("metadata", {}, executionContext({ metadata: { value } })),
      ).rejects.toThrow(TypeError);
    }
    expect(handler).not.toHaveBeenCalled();
  });

  it("preserves padded opaque context ids exactly", async () => {
    const handler = vi.fn(async (_args, context: ToolExecutionContext) => ({
      sessionId: context.sessionId,
      turnId: context.turnId,
      requestId: context.requestId,
      traceId: context.traceId,
      toolCallId: context.toolCallId,
    }));
    const registry = new ToolRegistry().register(
      { name: "ids", description: "ids", parameters: {}, risk: "read" },
      handler,
    );
    const context = executionContext({
      sessionId: " session ",
      turnId: " turn ",
      requestId: " request ",
      traceId: " trace ",
      toolCallId: " call ",
      idempotencyKey: " session : call ",
    });

    await expect(registry.execute("ids", {}, context)).resolves.toEqual({
      sessionId: " session ",
      turnId: " turn ",
      requestId: " request ",
      traceId: " trace ",
      toolCallId: " call ",
    });
  });

  it("applies the same exact overload dispatch to executeTool", async () => {
    registerTool(
      { name: "global_shape", description: "shape", parameters: {}, risk: "read" },
      async () => ({ ok: true }),
    );
    const untypedExecute = executeTool as (...args: unknown[]) => Promise<unknown>;

    await expect(untypedExecute("global_shape", {}, executionContext())).resolves.toEqual({
      ok: true,
    });
    await expect(untypedExecute("global_shape", {}, executionContext(), undefined)).rejects.toThrow(
      TypeError,
    );
    await expect(untypedExecute("principal", "global_shape", executionContext())).rejects.toThrow(
      TypeError,
    );
  });

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
          risk: "read",
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
      risk: "read" as const,
    };
    const registry = new ToolRegistry();
    registry.register(spec, async (args) => ({ value: args.value }));

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
        risk: "read",
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
    registry.register(
      { name: "ping", description: "d", parameters: {}, risk: "read" },
      async () => ({
        pong: true,
      }),
    );
    const result = await registry.execute("u", "ping", {});
    expect(result).toEqual({ pong: true });
  });

  it("duplicate registration throws", () => {
    const registry = new ToolRegistry();
    registry.register(
      { name: "dup", description: "d", parameters: {}, risk: "read" },
      async () => ({}),
    );
    expect(() =>
      registry.register(
        { name: "dup", description: "d", parameters: {}, risk: "read" },
        async () => ({}),
      ),
    ).toThrow(/already registered/);
  });

  it("execute throws for unknown tool", async () => {
    const registry = new ToolRegistry();
    await expect(registry.execute("u", "ghost", {})).rejects.toThrow(/Unknown tool/);
  });

  it("listSpecs excludes disabled by default", () => {
    const registry = new ToolRegistry();
    registry.register(
      { name: "on", description: "d", parameters: {}, risk: "read" },
      async () => ({}),
    );
    registry.register(
      { name: "off", description: "d", parameters: {}, enabled: false, risk: "read" },
      async () => ({}),
    );
    expect(registry.listSpecs().map((s) => s.name)).toEqual(["on"]);
  });

  it("listSpecs with enabledOnly:false returns all", () => {
    const registry = new ToolRegistry();
    registry.register(
      { name: "on", description: "d", parameters: {}, risk: "read" },
      async () => ({}),
    );
    registry.register(
      { name: "off", description: "d", parameters: {}, enabled: false, risk: "read" },
      async () => ({}),
    );
    expect(registry.listSpecs({ enabledOnly: false })).toHaveLength(2);
  });

  it("listSpecs filters by tag", () => {
    const registry = new ToolRegistry();
    registry.register(
      { name: "a", description: "d", parameters: {}, tags: ["payments"], risk: "read" },
      async () => ({}),
    );
    registry.register(
      { name: "b", description: "d", parameters: {}, risk: "read" },
      async () => ({}),
    );
    expect(registry.listSpecs({ tags: ["payments"] }).map((s) => s.name)).toEqual(["a"]);
  });

  it("two registries are isolated", () => {
    const r1 = new ToolRegistry();
    const r2 = new ToolRegistry();
    r1.register({ name: "x", description: "d", parameters: {}, risk: "read" }, async () => ({}));
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
    const handler = tool({ description: "Test", parameters: {}, risk: "read" }, async () => ({}));
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
      defaultContext: { principalId: "test-user" },
    });

    const s = "s-policy-denied";
    await seed(store, s);
    registerTool(
      { name: "dangerous_op", description: "d", parameters: {}, risk: "read" },
      async () => ({
        done: true,
      }),
    );

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

  it("emits TOOL_APPROVAL_REJECTED and TOOL_CALL_FAILED for destructive-risk tools with no approval handler", async () => {
    // When no approvalHandler is configured, the planner emits TOOL_APPROVAL_REJECTED
    // (for approval-aware consumers) AND TOOL_CALL_FAILED (so replaySession projects
    // the outcome into model history and the loop terminates cleanly).
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const policy = new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) });
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      bus,
      policy,
      defaultContext: { principalId: "test-user" },
    });

    const s = "s-policy-approval";
    await seed(store, s);
    registerTool(
      { name: "charge_card", description: "charges a card", parameters: {}, risk: "destructive" },
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
      expect(failedEvent.error).toBe("Tool approval unavailable");
      expect(failedEvent.error_code).toBe("APPROVAL_UNAVAILABLE");
    }
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(false);
  });

  it("executes tools normally when no policy is configured", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      bus,
      defaultContext: { principalId: "test-user" },
    });

    const s = "s-no-policy";
    await seed(store, s);
    registerTool(
      { name: "safe_op", description: "safe", parameters: {}, risk: "read" },
      async () => ({
        ok: true,
      }),
    );

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(true);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(false);
  });
});
