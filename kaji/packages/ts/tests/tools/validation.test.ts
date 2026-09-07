import { describe, expect, it, vi } from "vitest";
import { EventType } from "@/events/types";
import { ToolPlanner } from "@/tools/planner";
import type { ToolSpec } from "@/tools/registry";

const numericSpec: ToolSpec = {
  name: "price_check",
  description: "x",
  parameters: {
    type: "object",
    properties: { price: { type: "number" } },
    required: ["price"],
  },
  risk: "read",
};

const integerSpec: ToolSpec = {
  name: "count_check",
  description: "x",
  parameters: {
    type: "object",
    properties: { n: { type: "integer" } },
    required: ["n"],
  },
  risk: "read",
};

const noopEmit = async () => {};
const turnContext = { principalId: "test", requestId: "request", traceId: "trace" };

function makePlanner(spec: ToolSpec): ToolPlanner {
  return new ToolPlanner({
    executor: async () => ({ ok: true }),
    specs: new Map([[spec.name, spec]]),
  });
}

describe("ToolPlanner argument validation", () => {
  const unsafeArguments: Array<{
    name: string;
    path: string;
    build: () => Record<string, unknown>;
  }> = [
    { name: "undefined", path: "/value", build: () => ({ value: undefined }) },
    { name: "function", path: "/value", build: () => ({ value: () => "unsafe" }) },
    { name: "bigint", path: "/value", build: () => ({ value: 1n }) },
    { name: "symbol", path: "/value", build: () => ({ value: Symbol("unsafe") }) },
    {
      name: "cycle",
      path: "/self",
      build: () => {
        const value: Record<string, unknown> = {};
        value.self = value;
        return value;
      },
    },
  ];

  for (const unsafe of unsafeArguments) {
    it(`normalizes JSON-unsafe ${unsafe.name} arguments before emitting`, async () => {
      const executor = vi.fn();
      const planner = new ToolPlanner({
        executor,
        specs: new Map([
          ["unsafe", { name: "unsafe", description: "unsafe", parameters: {}, risk: "read" }],
        ]),
      });
      const events: Array<{ type: string; tool_args?: unknown }> = [];

      const result = await planner.executeBatch(
        "session-1",
        [{ id: "unsafe-1", name: "unsafe", arguments: unsafe.build() }],
        async (event) => {
          events.push(event);
        },
        "turn",
        turnContext,
      );

      expect(executor).not.toHaveBeenCalled();
      expect(events.map(({ type }) => type)).toEqual([
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
      ]);
      expect(events[0]?.tool_args).toEqual({ __parse_error: "invalid arguments" });
      expect(result[0]).toMatchObject({
        error_code: "INVALID_TOOL_ARGUMENTS",
        error_path: unsafe.path,
        retryable: false,
        outcome: "not_started",
      });
      expect((result[0] as { error: string }).error).toBe(
        `Tool arguments failed JSON safety validation at ${unsafe.path}`,
      );
      expect((result[0] as { error: string }).error.length).toBeLessThanOrEqual(200);
    });
  }

  it("rejects a reserved parse-error accessor without invoking it", async () => {
    let reads = 0;
    const args: Record<string, unknown> = {};
    Object.defineProperty(args, "__parse_error", {
      enumerable: true,
      get: () => {
        reads += 1;
        throw new Error("must not run");
      },
    });
    const executor = vi.fn();
    const planner = new ToolPlanner({
      executor,
      specs: new Map([
        ["unsafe", { name: "unsafe", description: "unsafe", parameters: {}, risk: "read" }],
      ]),
    });

    const result = await planner.executeBatch(
      "session-1",
      [{ id: "unsafe-accessor", name: "unsafe", arguments: args }],
      async () => {},
      "turn",
      turnContext,
    );

    expect(reads).toBe(0);
    expect(executor).not.toHaveBeenCalled();
    expect(result[0]).toMatchObject({
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/__parse_error",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("snapshots specs at construction", async () => {
    const spec: ToolSpec = {
      name: "snapshot",
      description: "snapshot",
      parameters: {
        type: "object",
        required: ["value"],
        properties: { value: { type: "string" } },
      },
      risk: "read",
    };
    const specs = new Map([[spec.name, spec]]);
    const planner = new ToolPlanner({ executor: async (_name, args) => args, specs });

    (spec.parameters.properties as any).value.type = "number";
    specs.clear();

    const accepted = await planner.executeBatch(
      "session-1",
      [{ id: "snapshot-1", name: "snapshot", arguments: { value: "stable" } }],
      noopEmit,
      "turn",
      turnContext,
    );
    const rejected = await planner.executeBatch(
      "session-1",
      [{ id: "snapshot-2", name: "snapshot", arguments: { value: 1 } }],
      noopEmit,
      "turn",
      turnContext,
    );

    expect(accepted[0]).toHaveProperty("result", { value: "stable" });
    expect(rejected[0]).toMatchObject({
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/value",
    });
  });

  it("rejects NaN as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeBatch(
      "session-1",
      [{ id: "c1", name: "price_check", arguments: { price: Number.NaN } }],
      noopEmit,
      "turn",
      turnContext,
    );
    expect(out[0]).toMatchObject({
      error: "Tool arguments failed JSON safety validation at /price",
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/price",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("rejects positive Infinity as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeBatch(
      "session-1",
      [
        {
          id: "c2",
          name: "price_check",
          arguments: { price: Number.POSITIVE_INFINITY },
        },
      ],
      noopEmit,
      "turn",
      turnContext,
    );
    expect(out[0]).toMatchObject({
      error: "Tool arguments failed JSON safety validation at /price",
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/price",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("rejects negative Infinity as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeBatch(
      "session-1",
      [
        {
          id: "c3",
          name: "price_check",
          arguments: { price: Number.NEGATIVE_INFINITY },
        },
      ],
      noopEmit,
      "turn",
      turnContext,
    );
    expect(out[0]).toMatchObject({
      error: "Tool arguments failed JSON safety validation at /price",
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/price",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("rejects NaN as an integer argument", async () => {
    const planner = makePlanner(integerSpec);
    const out = await planner.executeBatch(
      "session-1",
      [{ id: "c4", name: "count_check", arguments: { n: Number.NaN } }],
      noopEmit,
      "turn",
      turnContext,
    );
    expect(out[0]).toMatchObject({
      error: "Tool arguments failed JSON safety validation at /n",
      error_code: "INVALID_TOOL_ARGUMENTS",
      error_path: "/n",
      retryable: false,
      outcome: "not_started",
    });
  });

  it("accepts a finite number", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeBatch(
      "session-1",
      [{ id: "c5", name: "price_check", arguments: { price: 42 } }],
      noopEmit,
      "turn",
      turnContext,
    );
    expect("result" in out[0]!).toBe(true);
  });

  it("accepts a finite integer", async () => {
    const planner = makePlanner(integerSpec);
    const out = await planner.executeBatch(
      "session-1",
      [{ id: "c6", name: "count_check", arguments: { n: 7 } }],
      noopEmit,
      "turn",
      turnContext,
    );
    expect("result" in out[0]!).toBe(true);
  });
});
