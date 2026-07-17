import { afterEach, describe, expect, it, vi } from "vitest";

import {
  withRetry,
  type ModelProvider,
  type ModelProviderOptions,
  type ModelResponse,
  type ModelResponseChunk,
  type ProviderMessage,
} from "@/providers/base";
import { AnthropicProvider } from "@/providers/anthropic";
import { OpenAIProvider } from "@/providers/openai";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import type { Clock, TimerHandle, TimerScheduler } from "@/internal/uuid";
import { ProviderCancellationContractViolation, TurnTimeoutError } from "@/runtime/limits";
import { AgentBuilder } from "@/runtime/builder";
import { AgentRuntime } from "@/runtime/runtime";
import { InMemoryEventCommitter } from "@/events/committer";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import { MockProvider } from "@/providers/mock";
import {
  InMemorySessionTurnCoordinator,
  type ObservableCancellationToken,
  type SessionTurnCoordinator,
  type SessionTurnLease,
  type TurnLeaseOptions,
} from "@/runtime/session-turn-coordinator";
import { replaySession } from "@/sessions/replay";
import { SessionProjector } from "@/sessions/projector";
import { ToolExecutionController } from "@/tools/execution";
import {
  IdempotencyCapacityError,
  IdempotencyConflictError,
  toolTimedOut,
} from "@/tools/execution-errors";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";
import { ToolPlanner } from "@/tools/planner";
import type { MetricMeasurement, MetricsSink } from "@/observability";
import type { ToolSpec } from "@/tools/registry";

afterEach(() => {
  vi.useRealTimers();
});

class ProviderTestClock implements Clock {
  constructor(private monotonic = 0) {}

  nowWallSeconds(): number {
    return 1_700_000_000;
  }

  nowMonotonic(): number {
    return this.monotonic;
  }

  advance(milliseconds: number): void {
    this.monotonic += milliseconds;
  }
}

class ProviderTestScheduler implements TimerScheduler {
  private readonly timers: Array<{
    due: number;
    callback: () => void;
    cancelled: boolean;
  }> = [];

  constructor(private readonly clock: ProviderTestClock) {}

  get pendingCount(): number {
    return this.timers.filter((timer) => !timer.cancelled).length;
  }

  schedule(delayMs: number, callback: () => void): TimerHandle {
    const timer = { due: this.clock.nowMonotonic() + delayMs, callback, cancelled: false };
    this.timers.push(timer);
    return { cancel: () => (timer.cancelled = true) };
  }

  advance(milliseconds: number): void {
    this.clock.advance(milliseconds);
    for (const timer of this.timers) {
      if (!timer.cancelled && timer.due <= this.clock.nowMonotonic()) {
        timer.cancelled = true;
        timer.callback();
      }
    }
  }
}

class RuntimeControlledStream implements AsyncIterableIterator<ModelResponseChunk> {
  readonly entered = Promise.withResolvers<void>();
  readonly cancellationSeen = Promise.withResolvers<void>();
  readonly returnEntered = Promise.withResolvers<void>();
  private readonly nextRelease = Promise.withResolvers<void>();
  private readonly returnRelease = Promise.withResolvers<void>();
  private token: CancellationToken | undefined;
  private finished = false;
  private nextActive = false;
  returnCount = 0;
  returnDuringNext = false;

  constructor(
    private readonly options: {
      hostileNext?: boolean;
      hostileReturn?: boolean;
      nextError?: Error;
    } = {},
  ) {}

  bind(token: CancellationToken): void {
    this.token = token;
  }

  releaseNext(): void {
    this.nextRelease.resolve();
  }

  releaseReturn(): void {
    this.returnRelease.resolve();
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<ModelResponseChunk> {
    return this;
  }

  async next(): Promise<IteratorResult<ModelResponseChunk>> {
    if (this.finished) return { done: true, value: undefined };
    const token = this.token;
    if (token === undefined) throw new Error("stream was not bound to a cancellation token");
    this.nextActive = true;
    this.entered.resolve();
    const abortWake = Promise.withResolvers<void>();
    const onAbort = () => {
      this.cancellationSeen.resolve();
      if (!this.options.hostileNext) abortWake.resolve();
    };
    token.signal.addEventListener("abort", onAbort, { once: true });
    if (token.isCancelled) onAbort();
    try {
      await Promise.race([this.nextRelease.promise, abortWake.promise]);
      if (this.options.nextError !== undefined) throw this.options.nextError;
      this.finished = true;
      return { done: true, value: undefined };
    } finally {
      token.signal.removeEventListener("abort", onAbort);
      this.nextActive = false;
    }
  }

  async return(): Promise<IteratorResult<ModelResponseChunk>> {
    this.returnCount += 1;
    this.returnDuringNext ||= this.nextActive;
    this.returnEntered.resolve();
    if (this.options.hostileReturn) await this.returnRelease.promise;
    this.finished = true;
    return { done: true, value: undefined };
  }
}

class RuntimeRejectingStream implements AsyncIterableIterator<ModelResponseChunk> {
  readonly entered = Promise.withResolvers<void>();
  private token: CancellationToken | undefined;
  returnCount = 0;

  constructor(
    private readonly error: Error,
    private readonly immediate = false,
  ) {}

  bind(token: CancellationToken): void {
    this.token = token;
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<ModelResponseChunk> {
    return this;
  }

  next(): Promise<IteratorResult<ModelResponseChunk>> {
    this.entered.resolve();
    if (this.immediate) return Promise.reject(this.error);
    const token = this.token;
    if (token === undefined) return Promise.reject(new Error("stream was not bound"));
    return new Promise((_resolve, reject) => {
      token.signal.addEventListener("abort", () => reject(this.error), { once: true });
    });
  }

  async return(): Promise<IteratorResult<ModelResponseChunk>> {
    this.returnCount += 1;
    return { done: true, value: undefined };
  }
}

type RuntimeProviderStream = AsyncIterableIterator<ModelResponseChunk> & {
  bind(token: CancellationToken): void;
};

class RuntimeControlledProvider implements ModelProvider {
  calls = 0;

  constructor(private readonly streams: RuntimeProviderStream[]) {}

  async generate(): Promise<ModelResponse> {
    return { content: "", toolCalls: [] };
  }

  generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    this.calls += 1;
    const stream = this.streams.shift();
    if (stream === undefined) throw new Error("No controlled provider stream remains");
    if (!(options?.cancellationToken instanceof CancellationToken)) {
      throw new Error("Runtime did not supply an owned provider token");
    }
    stream.bind(options.cancellationToken);
    return stream as unknown as AsyncGenerator<ModelResponseChunk>;
  }
}

class FaultingAsyncCoordinator implements SessionTurnCoordinator {
  quarantineFailures = 0;
  releaseFailures = 0;
  clearFailures = 0;
  quarantineGate?: Promise<void>;
  releaseGate?: Promise<void>;
  clearGate?: Promise<void>;
  readonly quarantineStarted = Promise.withResolvers<void>();
  readonly releaseStarted = Promise.withResolvers<void>();
  readonly clearStarted = Promise.withResolvers<void>();

  constructor(readonly inner: InMemorySessionTurnCoordinator) {}

  async acquire(
    sessionId: string,
    token?: ObservableCancellationToken,
    options?: TurnLeaseOptions,
  ): Promise<SessionTurnLease> {
    return this.wrapLease(await this.inner.acquire(sessionId, token, options));
  }

  async quarantine(sessionId: string): Promise<void> {
    this.quarantineStarted.resolve();
    if (this.quarantineGate !== undefined) await this.quarantineGate;
    if (this.quarantineFailures > 0) {
      this.quarantineFailures -= 1;
      throw new Error("injected quarantine failure");
    }
    this.inner.quarantine(sessionId);
  }

  async clearQuarantine(sessionId: string): Promise<void> {
    this.clearStarted.resolve();
    if (this.clearGate !== undefined) await this.clearGate;
    if (this.clearFailures > 0) {
      this.clearFailures -= 1;
      throw new Error("injected clear failure");
    }
    this.inner.clearQuarantine(sessionId);
  }

  async runExclusive<T>(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
    operation: () => Promise<T>,
  ): Promise<T> {
    const lease = await this.acquire(sessionId, token);
    try {
      return await operation();
    } finally {
      await lease.release();
    }
  }

  private wrapLease(inner: SessionTurnLease): SessionTurnLease {
    return {
      transfer: () => this.wrapLease(inner.transfer()),
      release: async () => {
        this.releaseStarted.resolve();
        if (this.releaseGate !== undefined) await this.releaseGate;
        if (this.releaseFailures > 0) {
          this.releaseFailures -= 1;
          throw new Error("injected release failure");
        }
        await inner.release();
      },
    };
  }
}

async function waitUntil(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 1_000; attempt++) {
    if (predicate()) return;
    await Promise.resolve();
  }
  throw new Error("condition did not settle");
}

function providerDeadlineRuntime(
  provider: ModelProvider,
  clock: ProviderTestClock,
  scheduler: ProviderTestScheduler,
  coordinator: SessionTurnCoordinator,
  store: InMemoryEventStore,
  turnTimeoutMs = 1_000,
  metricsSink?: MetricsSink,
): AgentRuntime {
  return new AgentRuntime({
    provider,
    store,
    committer: new InMemoryEventCommitter(store),
    turnCoordinator: coordinator,
    tools: [],
    clock,
    timerScheduler: scheduler,
    turnExecutionLimits: { turnTimeoutMs, providerCancellationGraceMs: 2_000 },
    ...(metricsSink === undefined ? {} : { metricsSink }),
  });
}

describe("tool idempotency ledger", () => {
  it("expires completed entries by completion time while LRU access only affects eviction", async () => {
    let now = 0;
    const ledger = new InMemoryToolIdempotencyLedger({
      capacity: 2,
      completedTtlMs: 10,
      now: () => now,
    });
    const a = await ledger.claim("session", "a", "a");
    expect(a.status).toBe("owner");
    if (a.status !== "owner") return;
    await ledger.complete(a.claim, { value: "a" });
    now = 5;
    expect((await ledger.claim("session", "a", "a")).status).toBe("completed");
    const b = await ledger.claim("session", "b", "b");
    expect(b.status).toBe("owner");
    if (b.status !== "owner") return;
    await ledger.complete(b.claim, { value: "b" });
    now = 6;
    await ledger.claim("session", "a", "a");
    const c = await ledger.claim("session", "c", "c");
    expect(c.status).toBe("owner");
    expect((await ledger.claim("session", "b", "b")).status).toBe("owner");

    const ttlLedger = new InMemoryToolIdempotencyLedger({
      capacity: 2,
      completedTtlMs: 10,
      now: () => now,
    });
    now = 0;
    const expiring = await ttlLedger.claim("session", "a", "a");
    expect(expiring.status).toBe("owner");
    if (expiring.status !== "owner") return;
    await ttlLedger.complete(expiring.claim, { value: "a" });
    now = 11;
    expect((await ttlLedger.claim("session", "a", "a")).status).toBe("owner");
  });

  it("never evicts running or unknown entries and fails before a new claim", async () => {
    const ledger = new InMemoryToolIdempotencyLedger({ capacity: 2 });
    const running = await ledger.claim("session", "running", "running");
    const unknown = await ledger.claim("session", "unknown", "unknown");
    expect(running.status).toBe("owner");
    expect(unknown.status).toBe("owner");
    if (unknown.status !== "owner") return;
    await ledger.unknownOutcome(unknown.claim, toolTimedOut("unknown"));
    await expect(ledger.claim("session", "new", "new")).rejects.toBeInstanceOf(
      IdempotencyCapacityError,
    );
  });

  it("fails closed when one exact key is reused for different work", async () => {
    const ledger = new InMemoryToolIdempotencyLedger();
    await ledger.claim("session", "call", "first");
    await expect(ledger.claim("session", "call", "second")).rejects.toMatchObject({
      constructor: IdempotencyConflictError,
      error_code: "IDEMPOTENCY_CONFLICT",
    });
  });

  it("stores session and call identity separately even when IDs contain colons", async () => {
    const ledger = new InMemoryToolIdempotencyLedger();
    expect((await ledger.claim("a:b", "c", "first")).status).toBe("owner");
    expect((await ledger.claim("a", "b:c", "second")).status).toBe("owner");
  });

  it("detaches completed values and releases only completed entries for a session", async () => {
    const ledger = new InMemoryToolIdempotencyLedger();
    const claim = await ledger.claim("session", "call", "fingerprint");
    expect(claim.status).toBe("owner");
    if (claim.status !== "owner") return;
    const result = { nested: { value: 1 } };
    await ledger.complete(claim.claim, result);
    result.nested.value = 2;
    const replay = await ledger.claim("session", "call", "fingerprint");
    expect(replay).toMatchObject({ status: "completed", result: { nested: { value: 1 } } });
    expect(await ledger.releaseCompleted("session")).toBe(1);
    expect((await ledger.claim("session", "call", "fingerprint")).status).toBe("owner");
  });

  it("purges every settled entry while preserving running claims", async () => {
    const ledger = new InMemoryToolIdempotencyLedger();
    const completed = await ledger.claim("session", "completed", "completed-old");
    const unknown = await ledger.claim("session", "unknown", "unknown-old");
    const running = await ledger.claim("session", "running", "running");
    expect(completed.status).toBe("owner");
    expect(unknown.status).toBe("owner");
    expect(running.status).toBe("owner");
    if (completed.status !== "owner" || unknown.status !== "owner") return;
    await ledger.complete(completed.claim, { ok: true });
    await ledger.unknownOutcome(unknown.claim, toolTimedOut("unknown"));

    expect(await ledger.releaseSettled("session")).toBe(2);
    expect((await ledger.claim("session", "completed", "completed-new")).status).toBe("owner");
    expect((await ledger.claim("session", "unknown", "unknown-new")).status).toBe("owner");
    expect((await ledger.claim("session", "running", "running")).status).toBe("running");
  });

  it("uses a monotonic clock by default", async () => {
    const monotonic = vi.spyOn(globalThis.performance, "now").mockReturnValue(42);
    const wallClock = vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("wall clock must not drive ledger expiry");
    });
    try {
      const ledger = new InMemoryToolIdempotencyLedger();
      const claim = await ledger.claim("clock", "call", "fingerprint");
      expect(claim.status).toBe("owner");
      if (claim.status === "owner") await ledger.complete(claim.claim, { ok: true });
      expect(monotonic).toHaveBeenCalled();
    } finally {
      wallClock.mockRestore();
      monotonic.mockRestore();
    }
  });
});

function deeplyNestedResult(depth = 10_000): unknown {
  let value: unknown = null;
  for (let index = 0; index < depth; index++) value = { nested: value };
  return value;
}

describe("durable tool results", () => {
  it.each([
    ["function", () => undefined, "INVALID_DURABLE_VALUE"],
    ["nested function", { nested: () => undefined }, "INVALID_DURABLE_VALUE"],
    ["NaN", Number.NaN, "INVALID_DURABLE_VALUE"],
    ["unsafe integer", 2 ** 53, "INVALID_DURABLE_VALUE"],
    ["deeply nested", deeplyNestedResult(), "INVALID_DURABLE_VALUE"],
    ["oversized", { value: "😀".repeat(16_385) }, "EVENT_PAYLOAD_TOO_LARGE"],
  ] as const)(
    "maps %s to one public failure and a replayable internal tombstone",
    async (_label, bad, internalCode) => {
      const ledger = new InMemoryToolIdempotencyLedger();
      const controller = new ToolExecutionController({ ledger, limits: { timeoutMs: null } });
      const execute = vi.fn().mockResolvedValue(bad);
      const request = {
        name: "tool",
        args: {},
        context: {
          principalId: "principal",
          sessionId: "invalid-result",
          turnId: "turn",
          requestId: "request",
          traceId: "trace",
          toolCallId: "call",
          idempotencyKey: "invalid-result:call",
          signal: new AbortController().signal,
          metadata: {},
        },
        exclusive: false,
        onStarted: async () => {},
        execute,
      };

      await expect(controller.execute(request)).resolves.toMatchObject({
        status: "failed",
        error: {
          message: "Invalid tool result",
          error_code: "INVALID_TOOL_RESULT",
          retryable: false,
          outcome: "unknown",
        },
      });
      expect(execute).toHaveBeenCalledOnce();

      const tombstone = await ledger.claim("invalid-result", "call", '["tool",{}]');
      expect(tombstone).toMatchObject({
        status: "unknown",
        error: { error_code: internalCode, subject: "tool_result" },
      });

      await expect(controller.execute(request)).resolves.toMatchObject({
        status: "failed",
        error: {
          error_code: "INVALID_TOOL_RESULT",
          retryable: false,
          outcome: "unknown",
        },
      });
      expect(execute).toHaveBeenCalledOnce();
    },
  );

  it("keeps ledger completion I/O failures distinct from invalid results", async () => {
    const backing = new InMemoryToolIdempotencyLedger();
    const ledger: ToolIdempotencyLedger = {
      claim: (...args) => backing.claim(...args),
      async complete() {
        throw new Error("ledger unavailable");
      },
      retryableFailure: (...args) => backing.retryableFailure(...args),
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
    };
    const controller = new ToolExecutionController({ ledger, limits: { timeoutMs: null } });
    const execute = vi.fn().mockResolvedValue({ ok: true });
    const request = {
      name: "tool",
      args: {},
      context: {
        principalId: "principal",
        sessionId: "ledger-failure",
        turnId: "turn",
        requestId: "request",
        traceId: "trace",
        toolCallId: "call",
        idempotencyKey: "ledger-failure:call",
        signal: new AbortController().signal,
        metadata: {},
      },
      exclusive: false,
      onStarted: async () => {},
      execute,
    };

    await expect(controller.execute(request)).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_EXECUTION_FAILED", retryable: false, outcome: "unknown" },
    });
    const tombstone = await backing.claim("ledger-failure", "call", '["tool",{}]');
    expect(tombstone).toMatchObject({
      status: "unknown",
      error: { error_code: "TOOL_EXECUTION_FAILED" },
    });
    expect((tombstone as { error?: { subject?: unknown } }).error?.subject).toBeUndefined();

    await expect(controller.execute(request)).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_EXECUTION_FAILED" },
    });
    expect(execute).toHaveBeenCalledOnce();
  });

  it("keeps runtime turns and projection healthy after a hostile result", async () => {
    const store = new InMemoryEventStore();
    const execute = vi.fn().mockResolvedValue({ bad: () => undefined });
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ toolCall: { name: "poison", args: {} } }))
      .integration({
        register(registry) {
          registry.register(
            {
              name: "poison",
              description: "Return a hostile value",
              parameters: {},
              risk: "write",
            },
            execute,
          );
        },
      })
      .build({ store });

    const first = await runtime.turn("call it", {
      sessionId: "invalid-tool-result",
      context: { principalId: "principal" },
    });
    const failures = first.events.filter((event) => event.type === EventType.TOOL_CALL_FAILED);
    expect(failures).toHaveLength(1);
    expect(failures[0]).toMatchObject({
      error: "Invalid tool result",
      error_code: "INVALID_TOOL_RESULT",
      retryable: false,
      outcome: "unknown",
    });
    expect(first.events.some((event) => event.type === EventType.TOOL_CALL_COMPLETED)).toBe(false);
    expect(first.events.at(-1)?.type).toBe(EventType.AGENT_MESSAGE_COMPLETED);
    expect(execute).toHaveBeenCalledOnce();

    const projector = new SessionProjector("invalid-tool-result");
    await expect(projector.sync(store)).resolves.toBeGreaterThan(0);
    const firstHistory = await store.getEvents("invalid-tool-result");
    expect(() => replaySession(firstHistory)).not.toThrow();

    const second = await runtime.turn("continue", {
      sessionId: "invalid-tool-result",
      context: { principalId: "principal" },
    });
    expect(second.text).not.toBe("");
    expect(second.events.at(-1)?.type).toBe(EventType.AGENT_MESSAGE_COMPLETED);
    expect(execute).toHaveBeenCalledOnce();
    const secondHistory = await store.getEvents("invalid-tool-result");
    expect(() => replaySession(secondHistory)).not.toThrow();
  });
});

describe("provider fault matrix", () => {
  it("keeps late claim cleanup busy until drain makes purge safe", async () => {
    const backing = new InMemoryToolIdempotencyLedger();
    const claimEntered = Promise.withResolvers<void>();
    const releaseClaim = Promise.withResolvers<void>();
    const ledger: ToolIdempotencyLedger = {
      async claim(...args) {
        claimEntered.resolve();
        await releaseClaim.promise;
        return backing.claim(...args);
      },
      complete: (...args) => backing.complete(...args),
      retryableFailure: (...args) => backing.retryableFailure(...args),
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
      releaseSettled: (...args) => backing.releaseSettled(...args),
    };
    const controller = new ToolExecutionController({ ledger, limits: { timeoutMs: null } });
    const planner = new ToolPlanner({
      specs: new Map(),
      executionController: controller,
      executor: async () => ({}),
    });
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider({ reply: "unused" }),
      store,
      committer: new InMemoryEventCommitter(store),
      planner,
      tools: [],
    });
    const cancellation = new AbortController();
    const execution = controller.execute({
      name: "late-claim",
      args: {},
      context: {
        principalId: "principal",
        sessionId: "late-claim-session",
        turnId: "turn",
        requestId: "request",
        traceId: "trace",
        toolCallId: "late-call",
        idempotencyKey: "late-claim-session:late-call",
        signal: cancellation.signal,
        metadata: {},
      },
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({ ok: true }),
    });
    await claimEntered.promise;
    cancellation.abort();
    await expect(execution).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_CANCELLED", outcome: "not_started" },
    });

    await expect(runtime.purgeSession("late-claim-session")).rejects.toMatchObject({
      code: "SESSION_PURGE_BUSY",
      sessionId: "late-claim-session",
    });
    expect(await runtime.drainTools(0)).toEqual(["late-call"]);

    releaseClaim.resolve();
    expect(await runtime.drainTools(50)).toEqual([]);
    await expect(runtime.purgeSession("late-claim-session")).resolves.toBe(false);
    expect((await backing.claim("late-claim-session", "late-call", "reused")).status).toBe("owner");
  });

  it("clears SDK caches before awaiting a failing host ledger purge", async () => {
    const backing = new InMemoryToolIdempotencyLedger();
    const releaseEntered = Promise.withResolvers<void>();
    const releaseGate = Promise.withResolvers<void>();
    const ledger: ToolIdempotencyLedger = {
      claim: (...args) => backing.claim(...args),
      complete: (...args) => backing.complete(...args),
      retryableFailure: (...args) => backing.retryableFailure(...args),
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
      async releaseSettled() {
        releaseEntered.resolve();
        await releaseGate.promise;
        throw new Error("host ledger purge failed");
      },
    };
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "canary" }))
      .toolIdempotencyLedger(ledger)
      .build({ store });
    await runtime.turn("cache-canary", { sessionId: "ledger-failure" });
    expect(runtime.contextIndexStats("ledger-failure")).toBeDefined();

    const purge = runtime.purgeSession("ledger-failure");
    await releaseEntered.promise;
    expect(await store.getEvents("ledger-failure")).toEqual([]);
    expect(runtime.contextIndexStats("ledger-failure")).toBeUndefined();

    releaseGate.resolve();
    await expect(purge).rejects.toThrow("host ledger purge failed");
    expect(await store.getEvents("ledger-failure")).toEqual([]);
  });

  it("rejects purge while a turn owns or is setting up session-scoped runtime state", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const stream = new RuntimeControlledStream();
    const provider = new RuntimeControlledProvider([stream]);
    const coordinator = new InMemorySessionTurnCoordinator();
    const store = new InMemoryEventStore();
    const runtime = providerDeadlineRuntime(provider, clock, scheduler, coordinator, store, 10_000);

    const turn = runtime.turn("active", { sessionId: "active-purge" });
    await stream.entered.promise;
    await expect(runtime.purgeSession("active-purge")).rejects.toMatchObject({
      name: "SessionPurgeBusyError",
      code: "SESSION_PURGE_BUSY",
      sessionId: "active-purge",
    });

    stream.releaseNext();
    await expect(turn).resolves.toMatchObject({ sessionId: "active-purge" });
    await expect(runtime.purgeSession("active-purge")).resolves.toBe(true);
    expect(await runtime.history("active-purge")).toEqual([]);
  });

  it.each([
    { label: "before-output", midStream: false },
    { label: "mid-stream", midStream: true },
  ])("keeps a $label fault single-terminal, replayable, and recoverable", async ({ midStream }) => {
    const secret = "provider-private-secret";
    let calls = 0;
    const provider: ModelProvider = {
      async generate(): Promise<ModelResponse> {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        calls++;
        if (calls === 1) {
          if (midStream) yield { delta: "partial", toolCalls: [] };
          throw new Error(secret);
        }
        yield { delta: "recovered", toolCalls: [] };
      },
    };
    const store = new InMemoryEventStore();
    const coordinator = new InMemorySessionTurnCoordinator();
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      turnCoordinator: coordinator,
      tools: [],
    });

    await expect(runtime.turn("first", { sessionId: "provider-fault" })).rejects.toThrow(secret);
    const failedHistory = await store.getEvents("provider-fault");
    const failures = failedHistory.filter(({ type }) => type === EventType.AGENT_TURN_FAILED);
    expect(failures).toHaveLength(1);
    const failedTurnId = failures[0]!.turn_id;
    expect(JSON.stringify(failures[0])).not.toContain(secret);
    expect(
      failedHistory.some(
        (event) =>
          event.type === EventType.AGENT_MESSAGE_COMPLETED && event.turn_id === failedTurnId,
      ),
    ).toBe(false);
    expect(
      failedHistory
        .filter(
          (event) => event.type === EventType.AGENT_MESSAGE_DELTA && event.turn_id === failedTurnId,
        )
        .map((event) => ("delta" in event ? event.delta : undefined)),
    ).toEqual(midStream ? ["partial"] : []);
    expect(() => replaySession(failedHistory)).not.toThrow();
    expect(coordinator.entryCount).toBe(0);
    expect(coordinator.waitingCount).toBe(0);

    await expect(runtime.turn("second", { sessionId: "provider-fault" })).resolves.toMatchObject({
      text: "recovered",
    });
    const recoveredHistory = await store.getEvents("provider-fault");
    expect(() => replaySession(recoveredHistory)).not.toThrow();
    expect(coordinator.entryCount).toBe(0);
    expect(coordinator.waitingCount).toBe(0);
  });

  it("classifies a provider rejection caused by the owned deadline as a turn timeout", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const raw = new Error("provider rejected its owned cancellation");
    const stream = new RuntimeRejectingStream(raw);
    const coordinator = new InMemorySessionTurnCoordinator();
    const store = new InMemoryEventStore();
    const measurements: MetricMeasurement[] = [];
    const runtime = providerDeadlineRuntime(
      new RuntimeControlledProvider([stream]),
      clock,
      scheduler,
      coordinator,
      store,
      1_000,
      {
        record(measurement) {
          measurements.push(measurement);
        },
      },
    );

    const turn = runtime.turn("timeout", { sessionId: "deadline-reject" });
    await stream.entered.promise;
    scheduler.advance(1_000);

    await expect(turn).rejects.toMatchObject({
      constructor: TurnTimeoutError,
      phase: "provider_open",
      retryable: true,
      outcome: "unknown",
    });
    expect(
      (await store.getEvents("deadline-reject")).filter(
        (event) => event.type === EventType.AGENT_TURN_FAILED,
      ),
    ).toEqual([
      expect.objectContaining({
        error_code: "TURN_TIMEOUT",
        phase: "provider_open",
        retryable: true,
        outcome: "unknown",
      }),
    ]);
    expect(stream.returnCount).toBe(1);
    expect(coordinator.entryCount).toBe(0);
    expect(coordinator.waitingCount).toBe(0);
    expect(scheduler.pendingCount).toBe(0);
    expect(measurements.find(({ name }) => name === "kaji.provider.duration_ms")?.labels).toEqual({
      provider_family: "custom",
      status: "error",
    });
  });

  it("preserves a provider error that settles before the injected deadline", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const raw = new Error("provider failed first");
    const stream = new RuntimeRejectingStream(raw, true);
    const coordinator = new InMemorySessionTurnCoordinator();
    const runtime = providerDeadlineRuntime(
      new RuntimeControlledProvider([stream]),
      clock,
      scheduler,
      coordinator,
      new InMemoryEventStore(),
    );

    const turn = runtime.turn("fail", { sessionId: "provider-first" });
    await stream.entered.promise;
    await expect(turn).rejects.toBe(raw);
    expect(stream.returnCount).toBe(1);
    expect(coordinator.entryCount).toBe(0);
    expect(coordinator.waitingCount).toBe(0);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("labels caller cancellation as a cancelled provider operation", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const stream = new RuntimeControlledStream();
    const coordinator = new InMemorySessionTurnCoordinator();
    const measurements: MetricMeasurement[] = [];
    const runtime = providerDeadlineRuntime(
      new RuntimeControlledProvider([stream]),
      clock,
      scheduler,
      coordinator,
      new InMemoryEventStore(),
      10_000,
      {
        record(measurement) {
          measurements.push(measurement);
        },
      },
    );
    const token = new CancellationToken();

    const turn = runtime.turn("cancel", {
      sessionId: "caller-cancel",
      cancellationToken: token,
    });
    await stream.entered.promise;
    token.cancel();

    await expect(turn).resolves.toMatchObject({
      sessionId: "caller-cancel",
      accounting: {
        providerIterations: 0,
        usage: null,
        usageComplete: false,
        costUsd: null,
        costComplete: false,
      },
    });
    expect(measurements.find(({ name }) => name === "kaji.provider.duration_ms")?.labels).toEqual({
      provider_family: "custom",
      status: "cancelled",
    });
    expect(measurements.find(({ name }) => name === "kaji.turn.iterations")).toMatchObject({
      value: 0,
      labels: { outcome: "cancelled" },
    });
    expect(stream.returnCount).toBe(1);
    expect(coordinator.entryCount).toBe(0);
    expect(scheduler.pendingCount).toBe(0);
  });

  it.each([
    { label: "normal completion", nextError: undefined },
    { label: "an earlier provider error", nextError: new Error("provider failed first") },
  ])(
    "quarantines a hostile return after $label and drains it exactly once",
    async ({ nextError }) => {
      const clock = new ProviderTestClock();
      const scheduler = new ProviderTestScheduler(clock);
      const stream = new RuntimeControlledStream({ hostileReturn: true, nextError });
      const provider = new RuntimeControlledProvider([stream]);
      const coordinator = new InMemorySessionTurnCoordinator();
      const store = new InMemoryEventStore();
      const runtime = providerDeadlineRuntime(provider, clock, scheduler, coordinator, store);

      const turn = runtime.turn("hostile return", { sessionId: "hostile-return" });
      await stream.entered.promise;
      stream.releaseNext();
      await stream.returnEntered.promise;
      scheduler.advance(1_000);
      await waitUntil(() => scheduler.pendingCount === 1);
      scheduler.advance(2_000);

      let violation: unknown;
      try {
        await turn;
      } catch (error) {
        violation = error;
      }
      expect(violation).toBeInstanceOf(ProviderCancellationContractViolation);
      if (nextError !== undefined) {
        expect((violation as Error).cause).toBe(nextError);
      }
      expect(stream.returnCount).toBe(1);
      expect(stream.returnDuringNext).toBe(false);
      expect(coordinator.entryCount).toBe(1);
      const failures = (await store.getEvents("hostile-return")).filter(
        (event) => event.type === EventType.AGENT_TURN_FAILED,
      );
      expect(failures).toHaveLength(1);
      expect(failures[0]).toMatchObject({
        error_code: "PROVIDER_CANCELLATION_CONTRACT_VIOLATION",
        phase: "provider_open",
        retryable: false,
        outcome: "unknown",
      });

      stream.releaseReturn();
      await expect(runtime.drainProviders(1)).resolves.toEqual([]);
      expect(stream.returnCount).toBe(1);
      expect(coordinator.entryCount).toBe(0);
      expect(scheduler.pendingCount).toBe(0);
    },
  );

  it("retains a hostile provider lease across runtimes until drain and close only blocks", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const hostile = new RuntimeControlledStream({ hostileNext: true });
    const other = new RuntimeControlledStream();
    const recovered = new RuntimeControlledStream();
    other.releaseNext();
    recovered.releaseNext();
    const provider = new RuntimeControlledProvider([hostile, other, recovered]);
    const coordinator = new InMemorySessionTurnCoordinator();
    const store = new InMemoryEventStore();
    const runtime = providerDeadlineRuntime(provider, clock, scheduler, coordinator, store);
    const sibling = providerDeadlineRuntime(provider, clock, scheduler, coordinator, store, 10_000);

    const owner = runtime.turn("owner", { sessionId: "quarantine" });
    await hostile.entered.promise;
    const waiting = sibling.turn("waiting", { sessionId: "quarantine" });
    await waitUntil(() => coordinator.waitingCount === 1);
    scheduler.advance(1_000);
    await hostile.cancellationSeen.promise;
    await waitUntil(() => scheduler.pendingCount === 2);
    scheduler.advance(2_000);

    await expect(owner).rejects.toMatchObject({
      constructor: ProviderCancellationContractViolation,
      phase: "provider_open",
    });
    await expect(waiting).rejects.toBeInstanceOf(ProviderCancellationContractViolation);
    expect(coordinator.entryCount).toBe(1);
    expect(coordinator.waitingCount).toBe(0);
    expect(hostile.returnCount).toBe(0);
    await expect(runtime.purgeSession("quarantine")).rejects.toMatchObject({
      name: "SessionPurgeBusyError",
      code: "SESSION_PURGE_BUSY",
      sessionId: "quarantine",
    });

    await expect(sibling.turn("rejected", { sessionId: "quarantine" })).rejects.toBeInstanceOf(
      ProviderCancellationContractViolation,
    );
    expect(provider.calls).toBe(1);

    await expect(runtime.turn("other", { sessionId: "other-session" })).resolves.toMatchObject({
      sessionId: "other-session",
    });
    expect(provider.calls).toBe(2);

    const failedDrain = runtime.drainProviders(0);
    await waitUntil(() => scheduler.pendingCount === 1);
    scheduler.advance(0);
    await expect(failedDrain).resolves.toEqual(["quarantine"]);
    expect(coordinator.entryCount).toBe(1);

    runtime.close();
    await expect(runtime.turn("closed", { sessionId: "closed" })).rejects.toThrow(/closed/);
    expect(hostile.returnCount).toBe(0);

    hostile.releaseNext();
    await hostile.returnEntered.promise;
    await expect(runtime.drainProviders(1)).resolves.toEqual([]);
    expect(hostile.returnCount).toBe(1);
    expect(hostile.returnDuringNext).toBe(false);
    expect(coordinator.entryCount).toBe(0);

    await expect(sibling.turn("reused", { sessionId: "quarantine" })).resolves.toMatchObject({
      sessionId: "quarantine",
    });
    expect(provider.calls).toBe(3);
    expect(coordinator.entryCount).toBe(0);
    expect(coordinator.waitingCount).toBe(0);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("retains transferred ownership when an async quarantine hook fails", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const hostile = new RuntimeControlledStream({ hostileNext: true });
    const provider = new RuntimeControlledProvider([hostile]);
    const inner = new InMemorySessionTurnCoordinator();
    const coordinator = new FaultingAsyncCoordinator(inner);
    coordinator.quarantineFailures = 1;
    const runtime = providerDeadlineRuntime(
      provider,
      clock,
      scheduler,
      coordinator,
      new InMemoryEventStore(),
    );

    const turn = runtime.turn("hostile", { sessionId: "setup-failure" });
    await hostile.entered.promise;
    scheduler.advance(1_000);
    await hostile.cancellationSeen.promise;
    await waitUntil(() => scheduler.pendingCount === 1);
    scheduler.advance(2_000);

    await expect(turn).rejects.toThrow("injected quarantine failure");
    expect(inner.entryCount).toBe(1);

    hostile.releaseNext();
    await hostile.returnEntered.promise;
    await expect(runtime.drainProviders(1)).resolves.toEqual([]);
    expect(inner.entryCount).toBe(0);
  });

  it.each(["release", "clear"] as const)(
    "keeps a session quarantined when async %s cleanup fails",
    async (failure) => {
      const clock = new ProviderTestClock();
      const scheduler = new ProviderTestScheduler(clock);
      const hostile = new RuntimeControlledStream({ hostileNext: true });
      const provider = new RuntimeControlledProvider([hostile]);
      const inner = new InMemorySessionTurnCoordinator();
      const coordinator = new FaultingAsyncCoordinator(inner);
      const runtime = providerDeadlineRuntime(
        provider,
        clock,
        scheduler,
        coordinator,
        new InMemoryEventStore(),
      );

      const turn = runtime.turn("hostile", { sessionId: `${failure}-failure` });
      await hostile.entered.promise;
      scheduler.advance(1_000);
      await hostile.cancellationSeen.promise;
      await waitUntil(() => scheduler.pendingCount === 1);
      scheduler.advance(2_000);
      await expect(turn).rejects.toBeInstanceOf(ProviderCancellationContractViolation);

      hostile.releaseNext();
      await hostile.returnEntered.promise;
      if (failure === "release") coordinator.releaseFailures = 1;
      else coordinator.clearFailures = 1;
      await expect(runtime.drainProviders(1)).rejects.toThrow(`injected ${failure} failure`);

      expect(inner.entryCount).toBe(1);
      await expect(inner.acquire(`${failure}-failure`)).rejects.toBeInstanceOf(
        ProviderCancellationContractViolation,
      );
      await expect(runtime.drainProviders(1)).resolves.toEqual([]);
      expect(inner.entryCount).toBe(0);
    },
  );

  it("awaits async quarantine, release, and clear hooks in lifecycle order", async () => {
    const clock = new ProviderTestClock();
    const scheduler = new ProviderTestScheduler(clock);
    const hostile = new RuntimeControlledStream({ hostileNext: true });
    const provider = new RuntimeControlledProvider([hostile]);
    const inner = new InMemorySessionTurnCoordinator();
    const coordinator = new FaultingAsyncCoordinator(inner);
    const quarantineGate = Promise.withResolvers<void>();
    const releaseGate = Promise.withResolvers<void>();
    const clearGate = Promise.withResolvers<void>();
    coordinator.quarantineGate = quarantineGate.promise;
    coordinator.releaseGate = releaseGate.promise;
    coordinator.clearGate = clearGate.promise;
    const runtime = providerDeadlineRuntime(
      provider,
      clock,
      scheduler,
      coordinator,
      new InMemoryEventStore(),
    );

    const turn = runtime.turn("hostile", { sessionId: "async-lifecycle" });
    let turnSettled = false;
    void turn.then(
      () => {
        turnSettled = true;
      },
      () => {
        turnSettled = true;
      },
    );
    await hostile.entered.promise;
    scheduler.advance(1_000);
    await hostile.cancellationSeen.promise;
    await waitUntil(() => scheduler.pendingCount === 1);
    scheduler.advance(2_000);
    await coordinator.quarantineStarted.promise;
    await Promise.resolve();
    expect(turnSettled).toBe(false);

    quarantineGate.resolve();
    await expect(turn).rejects.toBeInstanceOf(ProviderCancellationContractViolation);
    hostile.releaseNext();
    await hostile.returnEntered.promise;

    const drain = runtime.drainProviders(1);
    let drainSettled = false;
    void drain.then(
      () => {
        drainSettled = true;
      },
      () => {
        drainSettled = true;
      },
    );
    await coordinator.releaseStarted.promise;
    await Promise.resolve();
    expect(drainSettled).toBe(false);
    expect(inner.entryCount).toBe(1);

    releaseGate.resolve();
    await coordinator.clearStarted.promise;
    await Promise.resolve();
    expect(drainSettled).toBe(false);
    expect(inner.entryCount).toBe(1);
    await expect(inner.acquire("async-lifecycle")).rejects.toBeInstanceOf(
      ProviderCancellationContractViolation,
    );

    clearGate.resolve();
    await expect(drain).resolves.toEqual([]);
    expect(inner.entryCount).toBe(0);
  });
});

describe("runtime fault handling", () => {
  it("disables opaque vendor retries when Kaji owns retry policy", async () => {
    class InspectableOpenAIProvider extends OpenAIProvider {
      createForTest() {
        return this.createClient();
      }
    }
    class InspectableAnthropicProvider extends AnthropicProvider {
      createForTest() {
        return this.createClient();
      }
    }
    const openai = await new InspectableOpenAIProvider({ apiKey: "test" }).createForTest();
    const anthropic = await new InspectableAnthropicProvider({ apiKey: "test" }).createForTest();
    expect((openai as unknown as { maxRetries: number }).maxRetries).toBe(0);
    expect((anthropic as unknown as { maxRetries: number }).maxRetries).toBe(0);
  });

  it("interrupts provider retry sleep and clears the pending timer", async () => {
    vi.useFakeTimers();
    const token = new CancellationToken();
    const rateLimited = Object.assign(new Error("rate limited"), { status: 429 });
    const request = vi.fn().mockRejectedValue(rateLimited);
    const pending = withRetry(request, { maxAttempts: 3, baseDelayMs: 60_000 }, token);
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    expect(vi.getTimerCount()).toBe(1);
    token.cancel();
    await expect(pending).rejects.toBeInstanceOf(CancellationError);
    expect(request).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("interrupts a structural cancellation token without an AbortSignal", async () => {
    vi.useFakeTimers();
    const token = { isCancelled: false };
    const rateLimited = Object.assign(new Error("rate limited"), { status: 429 });
    const request = vi.fn().mockRejectedValue(rateLimited);
    const pending = withRetry(request, { maxAttempts: 3, baseDelayMs: 60_000 }, token);
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    expect(vi.getTimerCount()).toBe(1);
    token.isCancelled = true;
    const rejected = expect(pending).rejects.toBeInstanceOf(CancellationError);
    await vi.advanceTimersByTimeAsync(10);
    await rejected;
    expect(request).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("uses one timer when no cancellation token was supplied", async () => {
    vi.useFakeTimers();
    const rateLimited = Object.assign(new Error("rate limited"), { status: 429 });
    const request = vi.fn().mockRejectedValueOnce(rateLimited).mockResolvedValueOnce("ok");
    const timer = vi.spyOn(globalThis, "setTimeout");
    const pending = withRetry(request, { maxAttempts: 2, baseDelayMs: 60_000 });
    await Promise.resolve();
    await Promise.resolve();
    expect(request).toHaveBeenCalledOnce();
    expect(timer).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60_000);
    await expect(pending).resolves.toBe("ok");
    expect(request).toHaveBeenCalledTimes(2);
    expect(timer).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears a drain timer when handlers settle before the deadline", async () => {
    vi.useFakeTimers();
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    const context = {
      principalId: "principal",
      sessionId: "session",
      turnId: "turn",
      requestId: "request",
      traceId: "trace",
      toolCallId: "call",
      idempotencyKey: "session:call",
      signal: new AbortController().signal,
      metadata: {},
    };
    await controller.execute({
      name: "quick",
      args: {},
      context,
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({ ok: true }),
    });
    expect(await controller.drain(60_000)).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears a running waiter's deadline timer when the owner settles first", async () => {
    vi.useFakeTimers();
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const request = (timeoutMs?: number) =>
      controller.execute({
        name: "shared",
        args: {},
        context: {
          principalId: "principal",
          sessionId: "waiter-timer",
          turnId: "turn",
          requestId: "request",
          traceId: "trace",
          toolCallId: "call",
          idempotencyKey: "waiter-timer:call",
          signal: new AbortController().signal,
          metadata: {},
        },
        ...(timeoutMs === undefined ? {} : { timeoutMs }),
        exclusive: false,
        onStarted: async () => {},
        execute: async () => {
          await gate;
          return { ok: true };
        },
      });
    const owner = request();
    await Promise.resolve();
    const waiter = request(60_000);
    await vi.waitFor(() => expect(vi.getTimerCount()).toBe(1));
    release();
    await Promise.all([owner, waiter]);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("shares one controller across explicit and dynamically rebuilt planners", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const spec: ToolSpec = {
      name: "stuck",
      description: "stuck",
      parameters: {},
      risk: "external_effect",
      parallel_safe: true,
      timeout_ms: 5,
    };
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    const explicitPlanner = new ToolPlanner({
      specs: new Map([[spec.name, spec]]),
      executionController: controller,
      executor: async () => gate,
    });
    const explicitRuntime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer,
      planner: explicitPlanner,
      tools: [spec],
    });
    await explicitPlanner.executeBatch(
      "explicit",
      [{ id: "explicit-call", name: "stuck", arguments: {} }],
      async () => {},
      "turn",
      { principalId: "principal" },
    );
    expect(await explicitRuntime.drainTools(0)).toEqual(["explicit-call"]);

    const dynamicStore = new InMemoryEventStore();
    const dynamicRuntime = new AgentRuntime({
      provider: new MockProvider(),
      store: dynamicStore,
      committer: new InMemoryEventCommitter(dynamicStore),
    });
    // Build through the dynamic path twice; both must retain the runtime owner.
    const runtimeController = (
      dynamicRuntime as unknown as { toolExecutionController: ToolExecutionController }
    ).toolExecutionController;
    const buildPlanner = (
      dynamicRuntime as unknown as { buildPlanner(tools: ToolSpec[]): ToolPlanner }
    ).buildPlanner.bind(dynamicRuntime);
    expect(buildPlanner([spec]).executionController).toBe(runtimeController);
    expect(buildPlanner([spec]).executionController).toBe(runtimeController);

    const builderStore = new InMemoryEventStore();
    const builtRuntime = new AgentBuilder()
      .provider(new MockProvider())
      .toolExecutionLimits({ maxParallel: 2 })
      .build({ store: builderStore });
    const builtController = (
      builtRuntime as unknown as { toolExecutionController: ToolExecutionController }
    ).toolExecutionController;
    const builtPlanner = (builtRuntime as unknown as { planner: ToolPlanner }).planner;
    expect(builtPlanner.executionController).toBe(builtController);
    expect(builtController.limits.maxParallel).toBe(2);

    release();
    expect(await explicitRuntime.drainTools(50)).toEqual([]);
  });

  it("rejects ambiguous planner and runtime controller configuration", () => {
    const controller = new ToolExecutionController();
    const ledger = new InMemoryToolIdempotencyLedger();
    const plannerOptions = {
      executor: async () => ({}),
      specs: new Map<string, ToolSpec>(),
      executionController: controller,
    };
    expect(
      () => new ToolPlanner({ ...plannerOptions, executionLimits: { maxParallel: 2 } }),
    ).toThrow(/executionController cannot be combined/);
    expect(() => new ToolPlanner({ ...plannerOptions, idempotencyLedger: ledger })).toThrow(
      /executionController cannot be combined/,
    );

    const planner = new ToolPlanner(plannerOptions);
    const store = new InMemoryEventStore();
    const options = {
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
      planner,
    };
    expect(() => new AgentRuntime({ ...options, toolExecutionLimits: { maxParallel: 2 } })).toThrow(
      /Explicit planner cannot be combined/,
    );
    expect(() => new AgentRuntime({ ...options, toolIdempotencyLedger: ledger })).toThrow(
      /Explicit planner cannot be combined/,
    );
  });

  it("rejects an explicit planner wired to a different approval committer", () => {
    const store = new InMemoryEventStore();
    const runtimeCommitter = new InMemoryEventCommitter(store);
    const plannerCommitter = new InMemoryEventCommitter(store);
    const planner = new ToolPlanner({
      executor: async () => ({}),
      approvalCommitter: plannerCommitter,
    });

    expect(
      () =>
        new AgentRuntime({
          provider: new MockProvider(),
          store,
          committer: runtimeCommitter,
          planner,
        }),
    ).toThrow(/approval committer must match/i);
  });

  it.each(["timeout", "cancel"] as const)(
    "bounds a slow durable claim by %s and cleans a late owner claim",
    async (mode) => {
      const backing = new InMemoryToolIdempotencyLedger();
      let releaseClaim!: () => void;
      const claimGate = new Promise<void>((resolve) => {
        releaseClaim = resolve;
      });
      let claimBlocked = true;
      let claimEntered!: () => void;
      const entered = new Promise<void>((resolve) => {
        claimEntered = resolve;
      });
      let cleanupFinished!: () => void;
      const cleaned = new Promise<void>((resolve) => {
        cleanupFinished = resolve;
      });
      const ledger: ToolIdempotencyLedger = {
        async claim(...args) {
          claimEntered();
          if (claimBlocked) await claimGate;
          return backing.claim(...args);
        },
        complete: (...args) => backing.complete(...args),
        async retryableFailure(...args) {
          await backing.retryableFailure(...args);
          cleanupFinished();
        },
        unknownOutcome: (...args) => backing.unknownOutcome(...args),
        releaseCompleted: (...args) => backing.releaseCompleted(...args),
      };
      const abort = new AbortController();
      const controller = new ToolExecutionController({
        ledger,
        limits: { timeoutMs: mode === "timeout" ? 5 : null },
      });
      const onStarted = vi.fn();
      const execute = vi.fn().mockResolvedValue({ ok: true });
      const request = {
        name: "slow-claim",
        args: {},
        context: {
          principalId: "principal",
          sessionId: `slow-claim-${mode}`,
          turnId: "turn",
          requestId: "request",
          traceId: "trace",
          toolCallId: "call",
          idempotencyKey: `slow-claim-${mode}:call`,
          signal: abort.signal,
          metadata: {},
        },
        exclusive: false,
        onStarted,
        execute,
      };
      const pending = controller.execute(request);
      await entered;
      if (mode === "cancel") abort.abort();
      await expect(pending).resolves.toMatchObject({
        status: "failed",
        error: {
          error_code: mode === "cancel" ? "TOOL_CANCELLED" : "TOOL_TIMEOUT",
          retryable: true,
          outcome: "not_started",
        },
      });
      expect(onStarted).not.toHaveBeenCalled();
      expect(execute).not.toHaveBeenCalled();
      claimBlocked = false;
      releaseClaim();
      await cleaned;

      const retryAbort = new AbortController();
      await expect(
        controller.execute({
          ...request,
          context: { ...request.context, signal: retryAbort.signal },
        }),
      ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
      expect(onStarted).toHaveBeenCalledOnce();
      expect(execute).toHaveBeenCalledOnce();
      expect(await controller.drain(0)).toEqual([]);
    },
  );
});
