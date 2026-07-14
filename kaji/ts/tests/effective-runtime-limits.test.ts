import { describe, expect, it } from "vitest";

import {
  AgentBuilder,
  AgentRuntime,
  InMemoryEventCommitter,
  InMemoryEventStore,
  ToolExecutionController,
  ToolPlanner,
  TurnTimeoutError,
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
    const store = new InMemoryEventStore();
    expect(
      () =>
        new AgentRuntime({
          provider: new MockProvider(),
          store,
          committer: new InMemoryEventCommitter(store),
          strategy: { maxToolIterations: value as unknown as number },
        }),
    ).toThrowError(new RangeError("maxToolIterations must be a positive integer"));
  });

  it("reports beta defaults as an immutable public type", () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
    });

    const limits: EffectiveRuntimeLimits = runtime.effectiveLimits();

    expect(limits).toEqual({
      maxToolIterations: 5,
      contextWindowTurns: 32,
      contextWindowCharacters: 100_000,
      toolMaxParallel: 4,
      toolTimeoutMs: 30_000,
      approvalTimeoutMs: 300_000,
      turnTimeoutMs: 120_000,
      providerCancellationGraceMs: 5_000,
      providerTextMaxBytes: 262_144,
      providerToolArgumentsMaxBytes: 65_536,
      providerResponseMaxBytes: 524_288,
      providerToolCallsMax: 64,
    });
    expect(Object.isFrozen(limits)).toBe(true);
  });

  it("reports builder overrides", () => {
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .strategy({ maxToolIterations: 2 })
      .contextWindow({ maxTurns: 7, maxCharacters: 1_234 })
      .toolExecutionLimits({ maxParallel: 3, timeoutMs: 1_500, approvalTimeoutMs: 2_500 })
      .turnExecutionLimits({
        turnTimeoutMs: 12_500,
        providerCancellationGraceMs: 250,
        providerTextMaxBytes: 1_024,
        providerToolArgumentsMaxBytes: 512,
        providerResponseMaxBytes: 2_048,
        providerToolCallsMax: 3,
      })
      .build();

    expect(runtime.effectiveLimits()).toEqual({
      maxToolIterations: 2,
      contextWindowTurns: 7,
      contextWindowCharacters: 1_234,
      toolMaxParallel: 3,
      toolTimeoutMs: 1_500,
      approvalTimeoutMs: 2_500,
      turnTimeoutMs: 12_500,
      providerCancellationGraceMs: 250,
      providerTextMaxBytes: 1_024,
      providerToolArgumentsMaxBytes: 512,
      providerResponseMaxBytes: 2_048,
      providerToolCallsMax: 3,
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
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
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
      turnTimeoutMs: 120_000,
      providerCancellationGraceMs: 5_000,
      providerTextMaxBytes: 262_144,
      providerToolArgumentsMaxBytes: 65_536,
      providerResponseMaxBytes: 524_288,
      providerToolCallsMax: 64,
    });
  });

  it("carries phase-specific timeout semantics", () => {
    const error = new TurnTimeoutError("tool", false, "unknown");
    expect(error).toMatchObject({
      code: "TURN_TIMEOUT",
      phase: "tool",
      retryable: false,
      outcome: "unknown",
      message: "Turn deadline exceeded during tool",
    });
  });

  it.each([
    ["invalid phase", ["invalid", true, "not_started"]],
    ["non-boolean retryable", ["queue", 1, "not_started"]],
    ["invalid outcome", ["queue", true, "invalid"]],
  ] as const)("rejects %s timeout semantics", (_label, args) => {
    expect(
      () => new TurnTimeoutError(args[0] as never, args[1] as never, args[2] as never),
    ).toThrow();
  });

  it.each([
    ["zero timeout", { turnTimeoutMs: 0 }],
    ["boolean timeout", { turnTimeoutMs: true }],
    ["NaN grace", { providerCancellationGraceMs: Number.NaN }],
    ["infinite byte cap", { providerTextMaxBytes: Number.POSITIVE_INFINITY }],
    ["fractional call cap", { providerToolCallsMax: 1.5 }],
  ])("rejects %s", (_label, turnExecutionLimits) => {
    expect(() =>
      new AgentBuilder()
        .provider(new MockProvider())
        .turnExecutionLimits(turnExecutionLimits as never)
        .build(),
    ).toThrow(/positive integer/);
  });
});
