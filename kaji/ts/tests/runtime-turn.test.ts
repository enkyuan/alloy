/**
 * Tests for AgentRuntime.turn — the one-call hello-world wrapper.
 */
import { describe, it, expect } from "vitest";
import {
  AgentBuilder,
  CancellationToken,
  InMemoryEventStore,
  InMemoryToolIdempotencyLedger,
  EventType,
  KajiEvent,
  SessionPurgeUnsupportedError,
  supportsSessionPurge,
  type EventStore,
  type MetricMeasurement,
  type MetricsSink,
  type ModelProvider,
  type ModelProviderOptions,
  type ModelResponseChunk,
  type ProviderMessage,
  type ToolIdempotencyLedger,
} from "@kaji/sdk";
import { MockProvider } from "@/providers/mock";

class NonPurgeableStore implements EventStore {
  private readonly inner = new InMemoryEventStore();
  readonly maxSessions = this.inner.maxSessions;

  append(...args: Parameters<EventStore["append"]>) {
    return this.inner.append(...args);
  }

  getEvents(...args: Parameters<EventStore["getEvents"]>) {
    return this.inner.getEvents(...args);
  }

  lastSequence(...args: Parameters<EventStore["lastSequence"]>) {
    return this.inner.lastSequence(...args);
  }
}

class ControlledPurgeStore extends InMemoryEventStore {
  readonly purgeEntered = Promise.withResolvers<void>();
  private readonly purgeRelease = Promise.withResolvers<void>();

  releasePurge(): void {
    this.purgeRelease.resolve();
  }

  override async purgeSession(sessionId: string): Promise<boolean> {
    this.purgeEntered.resolve();
    await this.purgeRelease.promise;
    return super.purgeSession(sessionId);
  }
}

class PurgeCanaryProvider implements ModelProvider {
  async generate() {
    return { content: "", toolCalls: [] };
  }

  async *generateStream(messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
    if (!messages.some((message) => message.role === "tool")) {
      yield {
        delta: "",
        toolCalls: [
          { id: "purge-canary-call", name: "purge_canary", args: { value: "args-canary" } },
        ],
      };
      return;
    }
    yield { delta: "assistant-", toolCalls: [] };
    yield { delta: "canary", toolCalls: [] };
  }
}

class RecordingProvider implements ModelProvider {
  readonly messages: ProviderMessage[][] = [];

  async generate() {
    return { content: "fresh-answer", toolCalls: [] };
  }

  async *generateStream(messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
    this.messages.push(structuredClone(messages));
    yield { delta: "fresh-answer", toolCalls: [] };
  }
}

class AccountingProvider implements ModelProvider {
  private call = 0;

  constructor(private readonly iterations: readonly (readonly ModelResponseChunk[])[]) {}

  async generate() {
    return { content: "", toolCalls: [] };
  }

  async *generateStream(): AsyncGenerator<ModelResponseChunk> {
    const chunks = this.iterations[this.call++];
    if (chunks === undefined) throw new Error("missing scripted provider iteration");
    for (const chunk of chunks) yield structuredClone(chunk);
  }
}

function accountingToolCall(id: string): ModelResponseChunk {
  return {
    delta: "",
    toolCalls: [{ id, name: "accounting_echo", args: {} }],
  };
}

function buildAccountingRuntime(
  provider: ModelProvider,
  options: {
    maxToolIterations?: number;
    metrics?: MetricsSink;
    onTool?: () => void | Promise<void>;
  } = {},
) {
  const store = new InMemoryEventStore();
  const builder = new AgentBuilder()
    .provider(provider)
    .integration({
      register(registry) {
        registry.register(
          { name: "accounting_echo", description: "accounting echo", parameters: {}, risk: "read" },
          async () => {
            await options.onTool?.();
            return { ok: true };
          },
        );
      },
    })
    .defaultContext({ principalId: "accounting-test" });
  if (options.maxToolIterations !== undefined) {
    builder.strategy({ maxToolIterations: options.maxToolIterations });
  }
  if (options.metrics !== undefined) builder.metricsSink(options.metrics);
  return { runtime: builder.build({ store }), store };
}

function turnIterations(measurements: readonly MetricMeasurement[]): number[] {
  return measurements
    .filter((measurement) => measurement.name === "kaji.turn.iterations")
    .map((measurement) => measurement.value);
}

function build(provider: MockProvider) {
  const store = new InMemoryEventStore();
  const runtime = new AgentBuilder().provider(provider).build({ store });
  return { runtime, store };
}

describe("AgentRuntime.turn", () => {
  it("returns text for a simple reply", async () => {
    const { runtime } = build(new MockProvider({ reply: "hello world" }));
    const r = await runtime.turn("ping");
    expect(r.text).toBe("hello world");
    expect(r.sessionId).toBeTruthy();
    expect(r.toolCallEvents).toEqual([]);
  });

  it("generates a fresh session id when none is given", async () => {
    const { runtime } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first");
    const r2 = await runtime.turn("second");
    expect(r1.sessionId).not.toBe(r2.sessionId);
  });

  it("reuses an existing session id", async () => {
    const { runtime, store } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first", { sessionId: "s-1" });
    const r2 = await runtime.turn("second", { sessionId: "s-1" });
    expect(r1.sessionId).toBe("s-1");
    expect(r2.sessionId).toBe("s-1");
    const events = await store.getEvents("s-1");
    expect(events.filter((e) => e.type === EventType.SESSION_CREATED)).toHaveLength(1);
  });

  it("emits TOOL_CALL_REQUESTED when the model calls a tool", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ toolCall: { name: "ping", args: {} } }))
      .integration({
        register(registry) {
          registry.register(
            { name: "ping", description: "ping", parameters: {}, risk: "read" },
            async () => ({ pong: true }),
          );
        },
      })
      .build({ store });
    const r = await runtime.turn("call ping", { context: { principalId: "test" } });
    expect(r.toolCallEvents.some((e) => e.type === EventType.TOOL_CALL_REQUESTED)).toBe(true);
  });

  it("skips tool execution when allowToolCalls is false", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration({
        register(registry) {
          registry.register(
            { name: "ping", description: "ping", parameters: {}, risk: "read" },
            async () => ({ pong: true }),
          );
        },
      })
      .strategy({ allowToolCalls: false })
      .build({ store });
    const r = await runtime.turn("call ping");
    expect(r.text).toBeTruthy();
    expect(r.toolCallEvents).toEqual([]);
    const events = await store.getEvents(r.sessionId);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_REQUESTED)).toBe(false);
  });

  it("scopes events to this turn only", async () => {
    const { runtime } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first", { sessionId: "s-1" });
    const r2 = await runtime.turn("second", { sessionId: "s-1" });
    expect(r1.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(true);
    expect(r2.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(false);
  });

  it("purges persisted and runtime-owned session state without disturbing shared-store peers", async () => {
    const store = new InMemoryEventStore({ maxSessions: 4, maxEventsPerSession: 100 });
    let executions = 0;
    const runtime = new AgentBuilder()
      .provider(new PurgeCanaryProvider())
      .integration({
        register(registry) {
          registry.register(
            { name: "purge_canary", description: "purge canary", parameters: {}, risk: "read" },
            async () => ({ value: `result-canary-${++executions}` }),
          );
        },
      })
      .defaultContext({ principalId: "purge-test" })
      .contextWindow({ maxTurns: 1, maxCharacters: 10_000 })
      .build({ store });
    const siblingProvider = new RecordingProvider();
    const sibling = new AgentBuilder().provider(siblingProvider).build({ store });

    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "purged-session" }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: "purged-session",
        content: "old-prompt",
      }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.AGENT_MESSAGE_COMPLETED,
        session_id: "purged-session",
        content: "old-answer",
      }),
    );

    await runtime.turn("prompt-canary", { sessionId: "purged-session" });
    await sibling.turn("sibling-warm-canary", { sessionId: "purged-session" });
    await sibling.turn("keep this", { sessionId: "retained-session" });
    const retainedBefore = await sibling.history("retained-session");
    const before = JSON.stringify(await runtime.history("purged-session"));
    for (const canary of ["prompt-canary", "args-canary", "result-canary-1", "assistant-canary"]) {
      expect(before).toContain(canary);
    }
    expect(runtime.contextDiagnostics("purged-session")).toMatchObject({ droppedTurns: 1 });
    expect(runtime.streamDiagnostics("purged-session")).toMatchObject({ inputFragments: 2 });
    expect(runtime.contextIndexStats("purged-session")).toBeDefined();
    expect(sibling.contextIndexStats("purged-session")).toBeDefined();

    await expect(runtime.purgeSession("purged-session")).resolves.toBe(true);
    expect(await runtime.history("purged-session")).toEqual([]);
    expect(runtime.contextDiagnostics("purged-session")).toBeUndefined();
    expect(runtime.streamDiagnostics("purged-session")).toBeUndefined();
    expect(runtime.contextIndexStats("purged-session")).toBeUndefined();
    expect(sibling.contextDiagnostics("purged-session")).toBeUndefined();
    expect(sibling.streamDiagnostics("purged-session")).toBeUndefined();
    expect(sibling.contextIndexStats("purged-session")).toBeUndefined();
    expect(await sibling.history("retained-session")).toEqual(retainedBefore);
    expect(sibling.contextIndexStats("retained-session")).toBeDefined();

    const caches = runtime as unknown as {
      projectors: Map<string, unknown>;
      projectionTails: Map<string, unknown>;
      activeProjectionSessions: Map<string, unknown>;
      turnEventCollectors: Map<string, unknown>;
      contextDiagnosticsBySession: Map<string, unknown>;
      streamDiagnosticsBySession: Map<string, unknown>;
      providerQuarantine: Map<string, unknown>;
    };
    expect(caches.projectors.has("purged-session")).toBe(false);
    expect(caches.projectionTails.has("purged-session")).toBe(false);
    expect(caches.activeProjectionSessions.has("purged-session")).toBe(false);
    expect(caches.turnEventCollectors.size).toBe(0);
    expect(caches.contextDiagnosticsBySession.has("purged-session")).toBe(false);
    expect(caches.streamDiagnosticsBySession.has("purged-session")).toBe(false);
    expect(caches.providerQuarantine.has("purged-session")).toBe(false);

    siblingProvider.messages.length = 0;
    const fresh = await sibling.turn("fresh-prompt", { sessionId: "purged-session" });
    expect(fresh.events[0]).toMatchObject({ type: EventType.SESSION_CREATED, sequence: 1 });
    const freshProviderInput = JSON.stringify(siblingProvider.messages);
    for (const canary of [
      "old-prompt",
      "old-answer",
      "prompt-canary",
      "args-canary",
      "result-canary-1",
      "assistant-canary",
      "sibling-warm-canary",
    ]) {
      expect(freshProviderInput).not.toContain(canary);
    }
    expect(executions).toBe(1);
  });

  it("rejects unsupported stores without partially clearing runtime caches", async () => {
    const store = new NonPurgeableStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "kept" }))
      .build({ store });
    await runtime.turn("keep", { sessionId: "unsupported" });
    const history = await runtime.history("unsupported");
    const stats = runtime.contextIndexStats("unsupported");
    const diagnostics = runtime.contextDiagnostics("unsupported");

    expect(supportsSessionPurge(store)).toBe(false);
    await expect(runtime.purgeSession("")).rejects.toThrow(TypeError);
    await expect(runtime.purgeSession("unsupported")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );
    expect(await runtime.history("unsupported")).toEqual(history);
    expect(runtime.contextIndexStats("unsupported")).toEqual(stats);
    expect(runtime.contextDiagnostics("unsupported")).toEqual(diagnostics);
  });

  it("rejects a legacy custom ledger before deleting store or cache state", async () => {
    const backing = new InMemoryToolIdempotencyLedger();
    const legacyLedger: ToolIdempotencyLedger = {
      claim: (...args) => backing.claim(...args),
      complete: (...args) => backing.complete(...args),
      retryableFailure: (...args) => backing.retryableFailure(...args),
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
    };
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "kept" }))
      .toolIdempotencyLedger(legacyLedger)
      .build({ store });
    await runtime.turn("keep", { sessionId: "legacy-ledger" });
    const history = await runtime.history("legacy-ledger");
    const stats = runtime.contextIndexStats("legacy-ledger");

    await expect(runtime.purgeSession("legacy-ledger")).rejects.toMatchObject({
      code: "SESSION_PURGE_UNSUPPORTED",
      sessionId: "legacy-ledger",
      component: "tool_idempotency_ledger",
    });
    expect(await runtime.history("legacy-ledger")).toEqual(history);
    expect(runtime.contextIndexStats("legacy-ledger")).toEqual(stats);
  });

  it("rejects attaching a new runtime while a shared-store purge is fenced", async () => {
    const store = new ControlledPurgeStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "old" }))
      .build({ store });
    await runtime.turn("old", { sessionId: "registration-race" });

    const purge = runtime.purgeSession("registration-race");
    await store.purgeEntered.promise;
    expect(() =>
      new AgentBuilder().provider(new MockProvider({ reply: "new" })).build({ store }),
    ).toThrowError(
      expect.objectContaining({
        code: "SESSION_PURGE_BUSY",
        sessionId: "registration-race",
      }),
    );

    store.releasePurge();
    await expect(purge).resolves.toBe(true);
  });

  it("uses defaultUuid (works without crypto.randomUUID)", async () => {
    // Simulate a restricted runtime where crypto.randomUUID is unavailable.
    // The runtime must not throw — defaultUuid falls back to a Math.random hex.
    const originalCrypto = globalThis.crypto;
    Object.defineProperty(globalThis, "crypto", {
      value: undefined,
      configurable: true,
    });
    try {
      const { runtime } = build(new MockProvider({ reply: "ok" }));
      const r = await runtime.turn("hi");
      expect(r.sessionId).toBeTruthy();
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        value: originalCrypto,
        configurable: true,
      });
    }
  });

  it("propagates provider errors", async () => {
    class FailingProvider {
      async generate() {
        throw new Error("provider boom");
      }
      // oxlint-disable-next-line require-yield -- throw is observed when the stream is consumed.
      async *generateStream(): AsyncGenerator<never> {
        throw new Error("provider boom");
      }
    }
    const { runtime } = build(new FailingProvider() as unknown as MockProvider);
    await expect(runtime.turn("hi")).rejects.toThrow("provider boom");
  });
});

describe("TurnResult.accounting", () => {
  it.each([
    { label: "tool-only", firstDelta: "", completionCount: 1 },
    { label: "mixed text and tool", firstDelta: "checking", completionCount: 2 },
  ])(
    "includes a $label provider iteration that durable completion totals cannot represent",
    async ({ firstDelta, completionCount }) => {
      const first = accountingToolCall("accounting-1");
      first.delta = firstDelta;
      first.usage = { input: 10, output: 2 };
      first.costUsd = 0.01;
      const provider = new AccountingProvider([
        [first],
        [{ delta: "done", toolCalls: [], usage: { input: 20, output: 3 }, costUsd: 0.02 }],
      ]);
      const measurements: MetricMeasurement[] = [];
      const { runtime } = buildAccountingRuntime(provider, {
        metrics: {
          record(measurement) {
            measurements.push(measurement);
          },
        },
      });

      const result = await runtime.turn("account for this");

      expect(result.accounting).toEqual({
        providerIterations: 2,
        usage: { input: 30, output: 5 },
        usageComplete: true,
        costUsd: expect.closeTo(0.03),
        costComplete: true,
      });
      const completions = result.events.filter(
        (event) => event.type === EventType.AGENT_MESSAGE_COMPLETED,
      );
      expect(completions).toHaveLength(completionCount);
      if (firstDelta === "") {
        expect(completions).toEqual([
          expect.objectContaining({
            content: "done",
            tokens: { input: 20, output: 3 },
            cost_usd: 0.02,
          }),
        ]);
      }
      expect(turnIterations(measurements)).toEqual([2]);
    },
  );

  it.each([
    {
      label: "all dimensions supplied",
      first: { usage: { input: 1, output: 2 }, costUsd: 0.125 },
      second: { usage: { input: 3, output: 4 }, costUsd: 0.25 },
      expected: {
        usage: { input: 4, output: 6 },
        usageComplete: true,
        costUsd: 0.375,
        costComplete: true,
      },
    },
    {
      label: "dimensions partially supplied",
      first: { usage: { input: 1, output: 2 } },
      second: { costUsd: 0.25 },
      expected: {
        usage: { input: 1, output: 2 },
        usageComplete: false,
        costUsd: 0.25,
        costComplete: false,
      },
    },
    {
      label: "dimensions never supplied",
      first: {},
      second: {},
      expected: {
        usage: null,
        usageComplete: false,
        costUsd: null,
        costComplete: false,
      },
    },
    {
      label: "explicit zeroes supplied",
      first: { usage: { input: 0, output: 0 }, costUsd: 0 },
      second: { usage: { input: 0, output: 0 }, costUsd: 0 },
      expected: {
        usage: { input: 0, output: 0 },
        usageComplete: true,
        costUsd: 0,
        costComplete: true,
      },
    },
  ])("reports honest completeness when $label", async ({ first, second, expected }) => {
    const provider = new AccountingProvider([
      [{ ...accountingToolCall("matrix-1"), ...first }],
      [{ delta: "done", toolCalls: [], ...second }],
    ]);
    const { runtime } = buildAccountingRuntime(provider);

    const result = await runtime.turn("matrix");

    expect(result.accounting).toEqual({ providerIterations: 2, ...expected });
  });

  it("uses the latest supplied metadata within an iteration without erasing it on omission", async () => {
    const { runtime } = buildAccountingRuntime(
      new AccountingProvider([
        [
          { delta: "", toolCalls: [], usage: { input: 1, output: 2 }, costUsd: 0.125 },
          { delta: "done", toolCalls: [], usage: { input: 3, output: 4 }, costUsd: 0.25 },
          { delta: "!", toolCalls: [] },
        ],
      ]),
    );

    const result = await runtime.turn("latest metadata");

    expect(result.accounting).toEqual({
      providerIterations: 1,
      usage: { input: 3, output: 4 },
      usageComplete: true,
      costUsd: 0.25,
      costComplete: true,
    });
  });

  it("counts an empty completed stream and freezes every accounting object", async () => {
    const { runtime } = buildAccountingRuntime(new AccountingProvider([[]]));

    const result = await runtime.turn("empty");

    expect(result.accounting).toEqual({
      providerIterations: 1,
      usage: null,
      usageComplete: false,
      costUsd: null,
      costComplete: false,
    });
    expect(Object.isFrozen(result.accounting)).toBe(true);

    const withUsage = await buildAccountingRuntime(
      new AccountingProvider([
        [{ delta: "done", toolCalls: [], usage: { input: 1, output: 2 }, costUsd: 0 }],
      ]),
    ).runtime.turn("immutable");
    expect(Object.isFrozen(withUsage.accounting.usage)).toBe(true);
    expect(() => {
      (withUsage.accounting as { providerIterations: number }).providerIterations = 99;
    }).toThrow(TypeError);
    expect(() => {
      (withUsage.accounting.usage as { input: number }).input = 99;
    }).toThrow(TypeError);
  });

  it("returns every completed iteration on max-tool exhaustion", async () => {
    const measurements: MetricMeasurement[] = [];
    const provider = new AccountingProvider([
      [{ ...accountingToolCall("exhaust-1"), usage: { input: 1, output: 2 }, costUsd: 0.1 }],
      [{ ...accountingToolCall("exhaust-2"), usage: { input: 3, output: 4 }, costUsd: 0.2 }],
    ]);
    const { runtime } = buildAccountingRuntime(provider, {
      maxToolIterations: 2,
      metrics: {
        record(measurement) {
          measurements.push(measurement);
        },
      },
    });

    const result = await runtime.turn("exhaust");

    expect(result.accounting).toMatchObject({
      providerIterations: 2,
      usage: { input: 4, output: 6 },
      usageComplete: true,
      costComplete: true,
    });
    expect(result.accounting.costUsd).toBeCloseTo(0.3);
    expect(result.events).toContainEqual(
      expect.objectContaining({ type: EventType.AGENT_TURN_EXHAUSTED, max_iterations: 2 }),
    );
    expect(turnIterations(measurements)).toEqual([2]);
  });

  it("keeps completed accounting when cancellation begins during tool execution", async () => {
    const token = new CancellationToken();
    const measurements: MetricMeasurement[] = [];
    const provider = new AccountingProvider([
      [{ ...accountingToolCall("cancel-tool"), usage: { input: 5, output: 1 }, costUsd: 0.5 }],
    ]);
    const { runtime } = buildAccountingRuntime(provider, {
      metrics: {
        record(measurement) {
          measurements.push(measurement);
        },
      },
      onTool: () => token.cancel(),
    });

    const result = await runtime.turn("cancel", { cancellationToken: token });

    expect(result.accounting).toEqual({
      providerIterations: 1,
      usage: { input: 5, output: 1 },
      usageComplete: true,
      costUsd: 0.5,
      costComplete: true,
    });
    expect(result.events).toContainEqual(
      expect.objectContaining({ type: EventType.CANCELLATION_COMPLETED }),
    );
    expect(turnIterations(measurements)).toEqual([1]);
  });

  it("excludes an interrupted provider stream and its partial metadata", async () => {
    let call = 0;
    const provider: ModelProvider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(_messages, _tools, options?: ModelProviderOptions) {
        call++;
        if (call === 1) {
          yield {
            ...accountingToolCall("cancel-provider"),
            usage: { input: 7, output: 2 },
            costUsd: 0.7,
          };
          return;
        }
        yield { delta: "partial", toolCalls: [], usage: { input: 100, output: 100 }, costUsd: 10 };
        (options?.cancellationToken as CancellationToken | undefined)?.cancel();
        yield { delta: "ignored", toolCalls: [], usage: { input: 200, output: 200 }, costUsd: 20 };
      },
    };
    const measurements: MetricMeasurement[] = [];
    const { runtime } = buildAccountingRuntime(provider, {
      metrics: {
        record(measurement) {
          measurements.push(measurement);
        },
      },
    });

    const result = await runtime.turn("interrupt");

    expect(result.accounting).toEqual({
      providerIterations: 1,
      usage: { input: 7, output: 2 },
      usageComplete: true,
      costUsd: 0.7,
      costComplete: true,
    });
    expect(result.events).toContainEqual(
      expect.objectContaining({ type: EventType.CANCELLATION_COMPLETED }),
    );
    expect(turnIterations(measurements)).toEqual([1]);
  });

  it.each([
    ["negative input", { usage: { input: -1, output: 0 } }],
    ["fractional output", { usage: { input: 0, output: 0.5 } }],
    ["unsafe input", { usage: { input: Number.MAX_SAFE_INTEGER + 1, output: 0 } }],
    ["non-finite output", { usage: { input: 0, output: Number.POSITIVE_INFINITY } }],
    ["negative cost", { costUsd: -0.01 }],
    ["non-finite cost", { costUsd: Number.POSITIVE_INFINITY }],
  ])("rejects tool-only %s metadata before exposing it", async (_label, metadata) => {
    const provider = new AccountingProvider([
      [{ ...accountingToolCall("invalid-metadata"), ...metadata } as ModelResponseChunk],
    ]);
    const { runtime } = buildAccountingRuntime(provider);

    await expect(runtime.turn("invalid")).rejects.toBeInstanceOf(RangeError);
  });

  it.each([
    [
      "token",
      { input: Number.MAX_SAFE_INTEGER, output: 0 },
      { input: 1, output: 0 },
      Number.MAX_VALUE / 4,
      Number.MAX_VALUE / 4,
    ],
    ["cost", { input: 0, output: 0 }, { input: 0, output: 0 }, Number.MAX_VALUE, Number.MAX_VALUE],
  ])(
    "rejects an unsafe %s aggregate instead of returning Infinity or wrapped totals",
    async (_label, firstUsage, secondUsage, firstCost, secondCost) => {
      const provider = new AccountingProvider([
        [
          {
            ...accountingToolCall("overflow-1"),
            usage: firstUsage,
            costUsd: firstCost,
          },
        ],
        [{ delta: "done", toolCalls: [], usage: secondUsage, costUsd: secondCost }],
      ]);
      const { runtime } = buildAccountingRuntime(provider);

      await expect(runtime.turn("overflow")).rejects.toBeInstanceOf(RangeError);
    },
  );

  it("keeps failed turns throwing instead of returning partial accounting", async () => {
    const provider: ModelProvider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      // oxlint-disable-next-line require-yield -- failure must occur when the stream is consumed.
      async *generateStream() {
        throw new Error("provider failed");
      },
    };
    const { runtime } = buildAccountingRuntime(provider);

    await expect(runtime.turn("fail")).rejects.toThrow("provider failed");
  });
});
