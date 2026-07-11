import { describe, expect, it } from "vitest";

import {
  AgentBuilder,
  AgentRuntime,
  EventBus,
  InMemoryEventStore,
  ToolExecutionController,
  ToolPlanner,
  type EffectiveRuntimeLimits,
} from "@kaji/sdk";
import { MockProvider } from "@/providers/mock";

describe("AgentRuntime effective limits", () => {
  it.each([
    ["zero", 0],
    ["negative", -1],
    ["boolean", true],
    ["fractional", 1.5],
    ["NaN", Number.NaN],
    ["positive infinity", Number.POSITIVE_INFINITY],
    ["negative infinity", Number.NEGATIVE_INFINITY],
  ])("rejects a %s maxToolIterations value", (_label, value) => {
    expect(
      () =>
        new AgentRuntime({
          provider: new MockProvider(),
          store: new InMemoryEventStore(),
          bus: new EventBus(),
          strategy: { maxToolIterations: value as unknown as number },
        }),
    ).toThrowError(new RangeError("maxToolIterations must be a positive integer"));
  });

  it("reports beta defaults as an immutable public type", () => {
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store: new InMemoryEventStore(),
      bus: new EventBus(),
    });

    const limits: EffectiveRuntimeLimits = runtime.effectiveLimits();

    expect(limits).toEqual({
      maxToolIterations: 5,
      contextWindowTurns: 32,
      contextWindowCharacters: 100_000,
      toolMaxParallel: 4,
      toolTimeoutMs: 30_000,
      approvalTimeoutMs: 300_000,
    });
    expect(Object.isFrozen(limits)).toBe(true);
  });

  it("reports builder overrides", () => {
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .strategy({ maxToolIterations: 2 })
      .contextWindow({ maxTurns: 7, maxCharacters: 1_234 })
      .toolExecutionLimits({ maxParallel: 3, timeoutMs: 1_500, approvalTimeoutMs: 2_500 })
      .build();

    expect(runtime.effectiveLimits()).toEqual({
      maxToolIterations: 2,
      contextWindowTurns: 7,
      contextWindowCharacters: 1_234,
      toolMaxParallel: 3,
      toolTimeoutMs: 1_500,
      approvalTimeoutMs: 2_500,
    });
  });

  it("uses an explicit planner's execution controller", () => {
    const executionController = new ToolExecutionController({
      limits: { maxParallel: 2, timeoutMs: null, approvalTimeoutMs: 6_000 },
    });
    const planner = new ToolPlanner({
      executor: async () => ({}),
      executionController,
    });
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store: new InMemoryEventStore(),
      bus: new EventBus(),
      planner,
      strategy: { maxToolIterations: 3 },
      contextWindow: { maxTurns: null, maxCharacters: 9_999 },
    });

    expect(runtime.effectiveLimits()).toEqual({
      maxToolIterations: 3,
      contextWindowTurns: null,
      contextWindowCharacters: 9_999,
      toolMaxParallel: 2,
      toolTimeoutMs: null,
      approvalTimeoutMs: 6_000,
    });
  });
});
