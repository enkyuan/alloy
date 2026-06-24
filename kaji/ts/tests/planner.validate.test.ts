import { describe, expect, it } from "vitest";
import { ToolPlanner } from "../src/tools/planner";
import type { ToolSpec } from "../src/tools/registry";

const numericSpec: ToolSpec = {
  name: "price_check",
  description: "x",
  parameters: {
    type: "object",
    properties: { price: { type: "number" } },
    required: ["price"],
  },
};

const integerSpec: ToolSpec = {
  name: "count_check",
  description: "x",
  parameters: {
    type: "object",
    properties: { n: { type: "integer" } },
    required: ["n"],
  },
};

const noopEmit = async () => {};

function makePlanner(spec: ToolSpec): ToolPlanner {
  return new ToolPlanner({
    executor: async () => ({ ok: true }),
    specs: new Map([[spec.name, spec]]),
  });
}

describe("ToolPlanner argument validation", () => {
  it("rejects NaN as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c1", name: "price_check", arguments: { price: Number.NaN } }],
      noopEmit,
    );
    expect("error" in out[0]!).toBe(true);
    expect((out[0]! as { error: string }).error).toMatch(/finite/i);
  });

  it("rejects positive Infinity as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [
        {
          id: "c2",
          name: "price_check",
          arguments: { price: Number.POSITIVE_INFINITY },
        },
      ],
      noopEmit,
    );
    expect("error" in out[0]!).toBe(true);
    expect((out[0]! as { error: string }).error).toMatch(/finite/i);
  });

  it("rejects negative Infinity as a number argument", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [
        {
          id: "c3",
          name: "price_check",
          arguments: { price: Number.NEGATIVE_INFINITY },
        },
      ],
      noopEmit,
    );
    expect("error" in out[0]!).toBe(true);
    expect((out[0]! as { error: string }).error).toMatch(/finite/i);
  });

  it("rejects NaN as an integer argument", async () => {
    const planner = makePlanner(integerSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c4", name: "count_check", arguments: { n: Number.NaN } }],
      noopEmit,
    );
    expect("error" in out[0]!).toBe(true);
    expect((out[0]! as { error: string }).error).toMatch(/finite/i);
  });

  it("accepts a finite number", async () => {
    const planner = makePlanner(numericSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c5", name: "price_check", arguments: { price: 42 } }],
      noopEmit,
    );
    expect("result" in out[0]!).toBe(true);
  });

  it("accepts a finite integer", async () => {
    const planner = makePlanner(integerSpec);
    const out = await planner.executeScatterGather(
      "session-1",
      [{ id: "c6", name: "count_check", arguments: { n: 7 } }],
      noopEmit,
    );
    expect("result" in out[0]!).toBe(true);
  });
});
