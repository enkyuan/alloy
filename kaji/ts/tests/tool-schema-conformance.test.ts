import { readFileSync } from "node:fs";

import { EventType } from "@/events/types";
import { ToolPlanner } from "@/tools/planner";
import { ToolRegistry, type ToolSpec } from "@/tools/registry";
import {
  ToolArgumentValidationError,
  ToolSchemaValidationError,
  ToolSchemaValidator,
} from "@/tools/validation";
import { describe, expect, it, vi } from "vitest";

interface ConformanceCase {
  name: string;
  kind?: "invalid_arguments" | "invalid_schema";
  schema: Record<string, unknown>;
  arguments: Record<string, unknown>;
  expectedPath?: string;
  expectedCode?: "INVALID_TOOL_ARGUMENTS" | "INVALID_TOOL_SCHEMA";
  expectedMessage?: string;
  retryable?: false;
  outcome?: "not_started";
}

function readCases(name: string): ConformanceCase[] {
  const fixture = JSON.parse(
    readFileSync(new URL(`../../contracts/tools/${name}`, import.meta.url), "utf8"),
  ) as { cases: ConformanceCase[] };
  return fixture.cases;
}

const validCases = readCases("conformance-valid.json");
const invalidCases = readCases("conformance-invalid.json");

function specFor(testCase: ConformanceCase): ToolSpec {
  return {
    name: "fixture_tool",
    description: testCase.name,
    parameters: testCase.schema,
    risk: "read",
  };
}

describe("shared tool-schema conformance", () => {
  const unsafeSchemas: Array<{
    name: string;
    path: string;
    build: () => Record<string, unknown>;
  }> = [
    { name: "undefined", path: "/unsafe", build: () => ({ unsafe: undefined }) },
    { name: "function", path: "/unsafe", build: () => ({ unsafe: () => "unsafe" }) },
    { name: "bigint", path: "/unsafe", build: () => ({ unsafe: 1n }) },
    { name: "symbol", path: "/unsafe", build: () => ({ unsafe: Symbol("unsafe") }) },
    {
      name: "cycle",
      path: "/self",
      build: () => {
        const schema: Record<string, unknown> = { type: "object" };
        schema.self = schema;
        return schema;
      },
    },
  ];

  for (const unsafe of unsafeSchemas) {
    it(`rejects JSON-unsafe ${unsafe.name} schemas atomically`, () => {
      const registry = new ToolRegistry();
      const handler = vi.fn().mockResolvedValue({ ok: true });

      expect(() =>
        registry.register(
          {
            name: "unsafe_schema",
            description: "unsafe schema",
            parameters: unsafe.build(),
            risk: "read",
          },
          handler,
        ),
      ).toThrowError(
        expect.objectContaining({
          code: "INVALID_TOOL_SCHEMA",
          path: unsafe.path,
          message: `Tool schema failed JSON safety validation at ${unsafe.path}`,
        }),
      );
      expect(registry.listSpecs({ enabledOnly: false })).toEqual([]);
      expect(() =>
        registry.register(
          {
            name: "unsafe_schema",
            description: "valid retry",
            parameters: { type: "object" },
            risk: "read",
          },
          handler,
        ),
      ).not.toThrow();
    });
  }

  for (const testCase of validCases) {
    it(`accepts: ${testCase.name}`, async () => {
      const validator = new ToolSchemaValidator(new Map([["fixture_tool", specFor(testCase)]]));
      await expect(validator.validate("fixture_tool", testCase.arguments)).resolves.toBeUndefined();
    });

    it(`executes through the registry: ${testCase.name}`, async () => {
      const handler = vi.fn().mockResolvedValue({ ok: true });
      const registry = new ToolRegistry().register(specFor(testCase), handler);

      await expect(registry.execute("user-1", "fixture_tool", testCase.arguments)).resolves.toEqual(
        { ok: true },
      );
      expect(handler).toHaveBeenCalledOnce();
    });
  }

  for (const testCase of invalidCases.filter(({ kind }) => kind === "invalid_arguments")) {
    it(`rejects before execution: ${testCase.name}`, async () => {
      const executor = vi.fn().mockResolvedValue({ should: "not run" });
      const planner = new ToolPlanner({
        executor,
        specs: new Map([["fixture_tool", specFor(testCase)]]),
      });
      const events: Array<Record<string, unknown>> = [];

      const result = await planner.executeBatch(
        "session-1",
        [
          {
            id: "call-1",
            name: "fixture_tool",
            arguments: testCase.arguments,
          },
        ],
        async (event) => {
          events.push(event);
        },
        "turn-1",
        { principalId: "test", requestId: "request", traceId: "trace" },
      );

      expect(executor).not.toHaveBeenCalled();
      expect(events.map(({ type }) => type)).toEqual([
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
      ]);
      expect(events).toHaveLength(2);
      expect(events).not.toContainEqual(
        expect.objectContaining({ type: EventType.TOOL_CALL_STARTED }),
      );
      expect(events[1]).toMatchObject({
        error_code: testCase.expectedCode,
        error_path: testCase.expectedPath,
        retryable: testCase.retryable,
        outcome: testCase.outcome,
      });
      expect(result[0]).toMatchObject({
        error_code: testCase.expectedCode,
        error_path: testCase.expectedPath,
        retryable: testCase.retryable,
        outcome: testCase.outcome,
      });
      expect(typeof (result[0] as { error: unknown }).error).toBe("string");
    });

    it(`rejects direct registry execution: ${testCase.name}`, async () => {
      const handler = vi.fn().mockResolvedValue({ should: "not run" });
      const registry = new ToolRegistry().register(specFor(testCase), handler);

      await expect(
        registry.execute("user-1", "fixture_tool", testCase.arguments),
      ).rejects.toMatchObject({
        code: testCase.expectedCode,
        path: testCase.expectedPath,
        retryable: testCase.retryable,
        outcome: testCase.outcome,
      });
      expect(handler).not.toHaveBeenCalled();
    });
  }

  for (const testCase of invalidCases.filter(({ kind }) => kind === "invalid_schema")) {
    it(`rejects schema during compilation: ${testCase.name}`, () => {
      expect.assertions(4);
      try {
        new ToolSchemaValidator(new Map([["fixture_tool", specFor(testCase)]]));
      } catch (error) {
        expect(error).toBeInstanceOf(ToolSchemaValidationError);
        const schemaError = error as ToolSchemaValidationError;
        expect(schemaError.normalized()).toEqual({
          code: testCase.expectedCode,
          path: testCase.expectedPath,
          message: testCase.expectedMessage,
        });
        expect(schemaError.retryable).toBe(testCase.retryable);
        expect(schemaError.outcome).toBe(testCase.outcome);
      }
    });

    it(`rejects schema atomically during registry registration: ${testCase.name}`, () => {
      const registry = new ToolRegistry();
      const handler = vi.fn().mockResolvedValue({ should: "not run" });

      expect(() => registry.register(specFor(testCase), handler)).toThrow(
        ToolSchemaValidationError,
      );
      expect(registry.listSpecs({ enabledOnly: false })).toEqual([]);
      expect(handler).not.toHaveBeenCalled();
      expect(() =>
        registry.register(
          {
            name: "fixture_tool",
            description: "valid replacement",
            parameters: { type: "object" },
            risk: "read",
          },
          handler,
        ),
      ).not.toThrow();
    });
  }

  it("rejects non-standard async Ajv schemas atomically", () => {
    const spec: ToolSpec = {
      name: "async_schema",
      description: "async schema",
      parameters: {
        $async: true,
        type: "object",
        required: ["value"],
        properties: { value: { type: "string" } },
      },
      risk: "read",
    };
    expect(() => new ToolSchemaValidator(new Map([[spec.name, spec]]))).toThrowError(
      expect.objectContaining({ code: "INVALID_TOOL_SCHEMA", path: "/" }),
    );

    const handler = vi.fn().mockResolvedValue({ should: "not run" });
    const registry = new ToolRegistry();
    expect(() => registry.register(spec, handler)).toThrowError(
      expect.objectContaining({ code: "INVALID_TOOL_SCHEMA", path: "/" }),
    );
    expect(registry.listSpecs({ enabledOnly: false })).toEqual([]);
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects every JSON-unsafe class through the public async validator", async () => {
    const validator = new ToolSchemaValidator(
      new Map([
        [
          "fixture_tool",
          { name: "fixture_tool", description: "safety", parameters: {}, risk: "read" },
        ],
      ]),
    );
    const sparse = new Array(1) as unknown[];
    const accessor: Record<string, unknown> = {};
    Object.defineProperty(accessor, "value", { enumerable: true, get: () => "unsafe" });
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    const arrayExpando: unknown[] & { extra?: unknown } = [];
    arrayExpando.extra = undefined;
    const arrayCycle: unknown[] & { extra?: unknown } = [];
    arrayCycle.extra = arrayCycle;
    const arrayAccessor: unknown[] = [];
    Object.defineProperty(arrayAccessor, "extra", { enumerable: true, get: () => "unsafe" });
    const indexedAccessor = new Array(1) as unknown[];
    Object.defineProperty(indexedAccessor, "0", { enumerable: true, get: () => "unsafe" });
    const arraySymbol: unknown[] = [];
    Object.defineProperty(arraySymbol, Symbol("unsafe"), { value: "unsafe" });
    const unsafeArguments: Array<{ args: Record<string, unknown>; path: string }> = [
      { args: { value: undefined }, path: "/value" },
      { args: { value: () => "unsafe" }, path: "/value" },
      { args: { value: 1n }, path: "/value" },
      { args: { value: Symbol("unsafe") }, path: "/value" },
      { args: { value: Number.NaN }, path: "/value" },
      { args: { value: sparse }, path: "/value/0" },
      { args: accessor, path: "/value" },
      { args: { value: new Date(0) }, path: "/value" },
      { args: cycle, path: "/self" },
      { args: { value: arrayExpando }, path: "/value/extra" },
      { args: { value: arrayCycle }, path: "/value/extra" },
      { args: { value: arrayAccessor }, path: "/value/extra" },
      { args: { value: indexedAccessor }, path: "/value/0" },
      { args: { value: arraySymbol }, path: "/value" },
    ];

    for (const { args, path } of unsafeArguments) {
      await expect(validator.validate("fixture_tool", args)).rejects.toMatchObject({
        code: "INVALID_TOOL_ARGUMENTS",
        path,
      });
    }
  });

  it("rejects array expando data before invoking a registry handler", async () => {
    const unsafe: unknown[] & { extra?: unknown } = [];
    unsafe.extra = unsafe;
    const handler = vi.fn().mockResolvedValue({ should: "not run" });
    const registry = new ToolRegistry().register(
      { name: "array_expando", description: "array expando", parameters: {}, risk: "read" },
      handler,
    );

    await expect(
      registry.execute("user-1", "array_expando", { value: unsafe }),
    ).rejects.toMatchObject({ code: "INVALID_TOOL_ARGUMENTS", path: "/value/extra" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("returns bounded argument errors without echoing rejected values", async () => {
    const secret = "sk-secret-value-that-must-not-appear";
    const validator = new ToolSchemaValidator(
      new Map([
        [
          "fixture_tool",
          {
            name: "fixture_tool",
            description: "redaction",
            parameters: {
              type: "object",
              properties: { token: { type: "string", pattern: "^allowed$" } },
            },
            risk: "read",
          },
        ],
      ]),
    );

    expect.assertions(4);
    try {
      await validator.validate("fixture_tool", { token: secret });
    } catch (error) {
      expect(error).toBeInstanceOf(ToolArgumentValidationError);
      const argumentError = error as ToolArgumentValidationError;
      expect(argumentError.normalized()).toEqual({
        code: "INVALID_TOOL_ARGUMENTS",
        path: "/token",
        message: "Tool arguments failed pattern validation at /token",
      });
      expect(argumentError.message.length).toBeLessThanOrEqual(200);
      expect(argumentError.message).not.toContain(secret);
    }
  });
});
