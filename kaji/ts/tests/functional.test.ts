import { describe, expect, it, vi } from "vitest";
import * as z from "zod";

import {
  AgentBuilder,
  BoundTool,
  EventType,
  functionTool,
  InMemoryEventStore,
  type ToolContext,
  ToolPlanner,
  ToolRegistry,
  ToolSchemaValidator,
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

  it("validates exactly once through AgentBuilder", async () => {
    let validationCalls = 0;
    const handler = vi.fn(async ({ value }: { value: string }) => ({ value }));
    const bound = functionTool(
      {
        name: "exact_once",
        description: "exact once",
        parameters: z.object({
          value: z.string().refine(() => {
            validationCalls += 1;
            return true;
          }),
        }),
      },
      handler,
    );
    const runtime = new AgentBuilder()
      .provider(
        new MockProvider({
          toolCall: { name: "fn_exact_once", args: { value: "original" } },
        }),
      )
      .tool(bound)
      .build();

    await runtime.send("session-exact-once", "run");

    expect(validationCalls).toBe(1);
    expect(handler).toHaveBeenCalledOnce();
    expect(handler.mock.calls[0]![0]).toEqual({ value: "original" });
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

  it("validates with Zod without applying defaults, coercions, or transforms", async () => {
    let transformCalls = 0;
    const original = {
      required: "present",
      defaulted: "provided",
      coerced: "42",
      transformed: "lowercase",
    };
    const handler = vi.fn(
      async (
        args: {
          required: string;
          defaulted?: string;
          coerced: unknown;
          transformed: string;
        },
        context: ToolContext,
      ) => ({ args, context }),
    );
    const bound = functionTool(
      {
        name: "validation_only",
        description: "validation only",
        parameters: z.object({
          required: z.string(),
          defaulted: z.string().default("generated"),
          coerced: z.coerce.number(),
          transformed: z.string().transform((value) => {
            transformCalls += 1;
            return value.toUpperCase();
          }),
        }),
      },
      handler,
    );

    const result = await bound.handler({ userId: "user-1" }, original);

    expect(result).toEqual({ args: original, context: { userId: "user-1" } });
    expect(handler).toHaveBeenCalledWith(original, { userId: "user-1" });
    expect(handler.mock.calls[0]![0]).not.toBe(original);
    expect(transformCalls).toBe(1);

    const registry = new ToolRegistry();
    bound.register(registry);
    await expect(registry.execute("user-2", "fn_validation_only", original)).resolves.toEqual({
      args: original,
      context: { userId: "user-2", db: undefined },
    });
    expect(transformCalls).toBe(2);
    expect(handler.mock.calls[1]![0]).not.toBe(original);

    const planner = new ToolPlanner({
      executor: (name, args) => registry.execute("user-3", name, args),
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });
    const events: Array<{ type: string }> = [];
    const plannerResult = await planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_validation_only", arguments: original }],
      async (event) => {
        events.push(event);
      },
    );

    expect(plannerResult[0]).toMatchObject({ result: { args: original } });
    expect(events.map(({ type }) => type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_STARTED,
      EventType.TOOL_CALL_COMPLETED,
    ]);
    expect(handler.mock.calls.map(([args]) => args)).toEqual([original, original, original]);
    expect(handler.mock.calls.every(([args]) => args !== original)).toBe(true);
    expect(transformCalls).toBe(3);
  });

  it("fails a flapping refinement before start and validates it once", async () => {
    let refinementCalls = 0;
    const handler = vi.fn(async () => ({ ok: true }));
    const bound = functionTool(
      {
        name: "flapping",
        description: "flapping",
        parameters: z.object({
          value: z.string().refine(() => {
            refinementCalls += 1;
            return refinementCalls > 1;
          }),
        }),
      },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const executor = vi.fn((name, args) => registry.execute("user-1", name, args));
    const planner = new ToolPlanner({
      executor,
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });
    const events: Array<{ type: string }> = [];

    const result = await planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_flapping", arguments: { value: "x" } }],
      async (event) => {
        events.push(event);
      },
    );

    expect(refinementCalls).toBe(1);
    expect(executor).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
    expect(events.map(({ type }) => type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(result[0]).toMatchObject({
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/value",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("supports a bound registry executor without duplicate validation", async () => {
    let validationCalls = 0;
    const handler = vi.fn(async () => ({ ok: true }));
    const bound = functionTool(
      {
        name: "bound_executor",
        description: "bound executor",
        parameters: z.object({
          value: z.string().refine(() => {
            validationCalls += 1;
            return true;
          }),
        }),
      },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const planner = new ToolPlanner({
      executor: registry.execute.bind(registry, "user-1"),
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });

    await planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_bound_executor", arguments: { value: "x" } }],
      async () => {},
    );

    expect(validationCalls).toBe(1);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("isolates execution arguments before an async refinement", async () => {
    let refinementCalls = 0;
    let refinementStarted!: () => void;
    let releaseRefinement!: () => void;
    const started = new Promise<void>((resolve) => {
      refinementStarted = resolve;
    });
    const release = new Promise<void>((resolve) => {
      releaseRefinement = resolve;
    });
    const original: { value: unknown } = { value: "validated" };
    const handler = vi.fn(async (args: { value: string }) => ({ args }));
    const bound = functionTool(
      {
        name: "isolated_async",
        description: "isolated async validation",
        parameters: z.object({
          value: z.string().refine(async (value) => {
            refinementCalls += 1;
            refinementStarted();
            await release;
            return value === "validated";
          }),
        }),
      },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const planner = new ToolPlanner({
      executor: registry.execute.bind(registry, "user-1"),
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });

    const pending = planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_isolated_async", arguments: original }],
      async () => {},
    );
    await started;
    original.value = 123;
    releaseRefinement();

    await expect(pending).resolves.toEqual([
      { id: "call-1", name: "fn_isolated_async", result: { args: { value: "validated" } } },
    ]);
    expect(refinementCalls).toBe(1);
    expect(handler).toHaveBeenCalledOnce();
    expect(handler.mock.calls[0]![0]).toEqual({ value: "validated" });
    expect(handler.mock.calls[0]![0]).not.toBe(original);
  });

  it("does not let an overlapping direct call consume a planner receipt", async () => {
    let refinementCalls = 0;
    let executorStarted!: () => void;
    let releaseExecutor!: () => void;
    const started = new Promise<void>((resolve) => {
      executorStarted = resolve;
    });
    const release = new Promise<void>((resolve) => {
      releaseExecutor = resolve;
    });
    const original = { value: "x" };
    const handler = vi.fn(async () => ({ ok: true }));
    const bound = functionTool(
      {
        name: "invocation_bound",
        description: "invocation-bound validation",
        parameters: z.object({
          value: z.string().refine(() => {
            refinementCalls += 1;
            return refinementCalls === 1;
          }),
        }),
      },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const planner = new ToolPlanner({
      executor: async (name, args) => {
        executorStarted();
        await release;
        return registry.execute("planned-user", name, args);
      },
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });

    const planned = planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_invocation_bound", arguments: original }],
      async () => {},
    );
    await started;
    await expect(
      registry.execute("direct-user", "fn_invocation_bound", original),
    ).rejects.toMatchObject({ code: "INVALID_TOOL_ARGUMENTS", path: "/value" });
    releaseExecutor();

    await expect(planned).resolves.toEqual([
      { id: "call-1", name: "fn_invocation_bound", result: { ok: true } },
    ]);
    expect(refinementCalls).toBe(2);
    expect(handler).toHaveBeenCalledOnce();
  });

  it("binds the original Zod parser when the tool is authored", async () => {
    const schema = z.object({ value: z.string() });
    const handler = vi.fn(async () => ({ ok: true }));
    const bound = functionTool(
      { name: "parser_snapshot", description: "parser snapshot", parameters: schema },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    const replacement = vi.fn(async () => ({ value: "bypassed" }));
    Object.defineProperty(schema, "parseAsync", { value: replacement });

    await expect(
      registry.execute("user-1", "fn_parser_snapshot", { value: 123 }),
    ).rejects.toMatchObject({ code: "INVALID_TOOL_ARGUMENTS", path: "/value" });
    expect(replacement).not.toHaveBeenCalled();
    expect(handler).not.toHaveBeenCalled();
  });

  it("uses Zod refinements through the public async validator", async () => {
    let refinementCalls = 0;
    const bound = functionTool(
      {
        name: "public_validator",
        description: "public validator",
        parameters: z.object({
          value: z.string().refine(() => {
            refinementCalls += 1;
            return false;
          }),
        }),
      },
      async () => ({ ok: true }),
    );
    const validator = new ToolSchemaValidator(new Map([[bound.spec.name, bound.spec]]));

    await expect(validator.validate(bound.spec.name, { value: "x" })).rejects.toMatchObject({
      code: "INVALID_TOOL_ARGUMENTS",
      path: "/value",
    });
    expect(refinementCalls).toBe(1);
  });

  it("revokes validation scope before a delayed second execution", async () => {
    let validationCalls = 0;
    const handler = vi.fn(async () => ({ ok: true }));
    const args = { value: "x" };
    const bound = functionTool(
      {
        name: "delayed",
        description: "delayed",
        parameters: z.object({
          value: z.string().refine(() => {
            validationCalls += 1;
            return validationCalls === 1;
          }),
        }),
      },
      handler,
    );
    const registry = new ToolRegistry();
    bound.register(registry);
    type DelayedOutcome = { value?: Record<string, unknown>; error?: unknown };
    let resolveDelayed!: (value: DelayedOutcome | Promise<DelayedOutcome>) => void;
    const delayed = new Promise<DelayedOutcome>((resolve) => {
      resolveDelayed = resolve;
    });
    const planner = new ToolPlanner({
      executor: async (name, executorArgs) => {
        setTimeout(
          () =>
            resolveDelayed(
              registry.execute("user-1", name, executorArgs).then(
                (value) => ({ value }),
                (error: unknown) => ({ error }),
              ),
            ),
          0,
        );
        return { scheduled: true };
      },
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });

    await planner.executeScatterGather(
      "session-1",
      [{ id: "call-1", name: "fn_delayed", arguments: args }],
      async () => {},
    );
    const replay = await delayed;

    expect(replay.error).toMatchObject({
      code: "INVALID_TOOL_ARGUMENTS",
      path: "/value",
    });
    expect(validationCalls).toBe(2);
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects missing required and async-refinement failures before the handler", async () => {
    const handler = vi.fn(async () => ({ ok: true }));
    const bound = functionTool(
      {
        name: "refined",
        description: "refined",
        parameters: z.object({
          required: z.string(),
          approved: z.string().refine(async (value) => value === "yes"),
        }),
      },
      handler,
    );

    await expect(bound.handler({ userId: "user-1" }, { approved: "yes" })).rejects.toThrow();
    await expect(
      bound.handler({ userId: "user-1" }, { required: "present", approved: "no" }),
    ).rejects.toThrow();
    expect(handler).not.toHaveBeenCalled();

    const registry = new ToolRegistry();
    bound.register(registry);
    const executor = vi.fn();
    const planner = new ToolPlanner({
      executor,
      specs: new Map(registry.listSpecs().map((spec) => [spec.name, spec])),
    });
    const events: Array<{ type: string }> = [];
    const result = await planner.executeScatterGather(
      "session-1",
      [
        {
          id: "call-1",
          name: "fn_refined",
          arguments: { required: "present", approved: "no" },
        },
      ],
      async (event) => {
        events.push(event);
      },
    );

    expect(executor).not.toHaveBeenCalled();
    expect(events.map(({ type }) => type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(result[0]).toMatchObject({
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/approved",
      retryable: false,
      outcome: "not_started",
    });
  });
});
