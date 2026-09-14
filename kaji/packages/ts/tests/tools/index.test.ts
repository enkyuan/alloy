import { afterEach, describe, expect, it, vi } from "vitest";
import * as z from "zod";

import { listToolSpecs, registerTool, toolSpecFromSchema } from "@/index";
import { ToolRegistry, clearTools, executeTool } from "@/tools/registry";
import { ToolSchemaValidator } from "@/tools/validation";
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

    const result = await executeTool(
      "get_weather",
      { city: "Seattle" },
      executionContext({ principalId: "user-1" }),
    );
    expect(result).toEqual({ user: "user-1", city: "Seattle", tempF: 68 });
  });

  it("rejects a duplicate registration", () => {
    const spec = toolSpecFromSchema("dup", "d", z.object({}), "read");
    registerTool(spec, async () => ({}));
    expect(() => registerTool(spec, async () => ({}))).toThrow(/already registered/);
  });

  it("throws when executing an unknown tool", async () => {
    await expect(executeTool("nope", {}, executionContext({ principalId: "u" }))).rejects.toThrow(
      /Unknown tool/,
    );
  });

  it("requires the canonical process-default execution signature", async () => {
    registerTool(
      { name: "global_shape", description: "shape", parameters: {}, risk: "read" },
      async () => ({ ok: true }),
    );
    const execute = executeTool as (...args: unknown[]) => Promise<unknown>;

    await expect(execute("global_shape", {}, executionContext())).resolves.toEqual({ ok: true });
    await expect(execute("global_shape", {}, executionContext(), undefined)).rejects.toThrow(
      TypeError,
    );
    await expect(execute("principal", "global_shape", {})).rejects.toThrow(TypeError);
  });

  it("passes an injected db handle through the context", async () => {
    const db = { marker: true };
    registerTool(
      toolSpecFromSchema("needs_db", "d", z.object({}), "read"),
      async (_args, context) => ({
        sawDb: context.db === db,
      }),
    );
    const result = await executeTool("needs_db", {}, executionContext({ principalId: "u", db }));
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

  it("requires the canonical registry execution signature", async () => {
    const registry = new ToolRegistry().register(
      { name: "shape", description: "shape", parameters: {}, risk: "read" },
      async () => ({ ok: true }),
    );
    const execute = registry.execute.bind(registry) as (...args: unknown[]) => Promise<unknown>;

    await expect(execute("shape", {}, executionContext())).resolves.toEqual({ ok: true });
    await expect(execute("shape", {}, executionContext(), undefined)).rejects.toThrow(TypeError);
    await expect(execute("principal", "shape", {})).rejects.toThrow(TypeError);
    await expect(execute("shape", {}, { principalId: "partial" })).rejects.toThrow(TypeError);
    await expect(execute("shape", {})).rejects.toThrow(TypeError);
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

    await expect(
      registry.execute("snapshot", { value: "stable" }, executionContext({ principalId: "u" })),
    ).resolves.toEqual({ value: "stable" });
    await expect(
      registry.execute("snapshot", { value: 1 }, executionContext({ principalId: "u" })),
    ).rejects.toMatchObject({
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
    await expect(
      registry.execute("immutable", { value: "stable" }, executionContext({ principalId: "u" })),
    ).resolves.toEqual({ ok: true });
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
    await expect(
      registry.execute("ghost", {}, executionContext({ principalId: "u" })),
    ).rejects.toThrow(/Unknown tool/);
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
});
