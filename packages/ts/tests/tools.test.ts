import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import {
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
});
