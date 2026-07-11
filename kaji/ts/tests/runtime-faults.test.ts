import { afterEach, describe, expect, it, vi } from "vitest";

import { withRetry } from "@/providers/base";
import { AnthropicProvider } from "@/providers/anthropic";
import { OpenAIProvider } from "@/providers/openai";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import { AgentBuilder } from "@/runtime/builder";
import { AgentRuntime } from "@/runtime/runtime";
import { InMemoryEventCommitter } from "@/events/committer";
import { InMemoryEventStore } from "@/events/store";
import { MockProvider } from "@/providers/mock";
import { ToolExecutionController } from "@/tools/execution";
import {
  IdempotencyCapacityError,
  IdempotencyConflictError,
  toolTimedOut,
} from "@/tools/execution-errors";
import { InMemoryToolIdempotencyLedger, type ToolIdempotencyLedger } from "@/tools/idempotency";
import { ToolPlanner } from "@/tools/planner";
import type { ToolSpec } from "@/tools/registry";

afterEach(() => {
  vi.useRealTimers();
});

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
    await explicitPlanner.executeScatterGather(
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
