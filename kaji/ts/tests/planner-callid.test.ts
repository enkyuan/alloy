import { describe, expect, it } from "vitest";
import { ToolPlanner } from "@/tools/planner";
import type { ToolSpec } from "@/tools/registry";

const noopSpec: ToolSpec = {
  name: "noop",
  description: "x",
  parameters: { type: "object" },
  risk: "read",
};

const noopEmit = async () => {};
const turnContext = {
  principalId: "test",
  requestId: "request",
  traceId: "trace",
};

describe("ToolPlanner uuid injection", () => {
  it("uses an injected uuid factory for missing call ids", async () => {
    let counter = 0;
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([[noopSpec.name, noopSpec]]),
      uuid: () => `fixed-${++counter}`,
    });

    const out = await planner.executeScatterGather(
      "s1",
      [{ name: "noop", arguments: {} }],
      noopEmit,
      "turn",
      turnContext,
    );

    expect((out[0] as { id: string }).id).toBe("fixed-1");
  });

  it("calls the factory once per missing-id call", async () => {
    let counter = 0;
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([[noopSpec.name, noopSpec]]),
      uuid: () => `gen-${++counter}`,
    });

    const out = await planner.executeScatterGather(
      "s1",
      [
        { name: "noop", arguments: {} },
        { name: "noop", arguments: {} },
        { name: "noop", arguments: {} },
      ],
      noopEmit,
      "turn",
      turnContext,
    );

    const ids = out.map((r) => (r as { id: string }).id);
    expect(ids).toEqual(["gen-1", "gen-2", "gen-3"]);
  });

  it("preserves an explicit call id and does not call the factory", async () => {
    let called = 0;
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([[noopSpec.name, noopSpec]]),
      uuid: () => {
        called += 1;
        return "should-not-be-used";
      },
    });

    const out = await planner.executeScatterGather(
      "s1",
      [{ id: "caller-id", name: "noop", arguments: {} }],
      noopEmit,
      "turn",
      turnContext,
    );

    expect((out[0] as { id: string }).id).toBe("caller-id");
    expect(called).toBe(0);
  });

  it("produces a uuid-shaped default id when no factory is injected", async () => {
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([[noopSpec.name, noopSpec]]),
    });

    const out = await planner.executeScatterGather(
      "s1",
      [{ name: "noop", arguments: {} }],
      noopEmit,
      "turn",
      turnContext,
    );

    const id = (out[0] as { id: string }).id;
    // 8-4-4-4-12 hex shape covers both crypto.randomUUID() and the
    // Math.random fallback in defaultUuid().
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });
});
