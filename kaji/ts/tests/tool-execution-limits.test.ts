import { describe, expect, it, vi } from "vitest";

import { EventType } from "@/events/types";
import { StoredKajiEvent } from "@/events/schemas";
import { ToolExecutionController } from "@/tools/execution";
import { ToolExecutionError, toolTimedOut } from "@/tools/execution-errors";
import { InMemoryToolIdempotencyLedger } from "@/tools/idempotency";
import { ToolPlanner } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";
import type { ToolExecutionContext } from "@/runtime/context";
import type { ToolSpec } from "@/tools/registry";

const TURN = { principalId: "principal", requestId: "request", traceId: "trace" };

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function spec(name: string, options: Partial<ToolSpec> = {}): ToolSpec {
  return { name, description: name, parameters: {}, risk: "read", ...options };
}

function context(
  sessionId: string,
  toolCallId: string,
  signal: AbortSignal = new AbortController().signal,
): ToolExecutionContext {
  return {
    principalId: "principal",
    sessionId,
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId,
    idempotencyKey: `${sessionId}:${toolCallId}`,
    signal,
    metadata: {},
  };
}

describe("bounded tool execution", () => {
  it("caps parallel-safe handlers at four and flushes results and terminals in provider order", async () => {
    let active = 0;
    let peak = 0;
    const executor = vi.fn(async (_name, args: Readonly<Record<string, unknown>>) => {
      active++;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, (20 - Number(args.index)) % 5));
      active--;
      return { index: args.index };
    });
    const tool = spec("parallel", { parallel_safe: true });
    const planner = new ToolPlanner({ executor, specs: new Map([[tool.name, tool]]) });
    const events: Array<{ type: string; tool_call_id?: string }> = [];
    const results = await planner.executeBatch(
      "parallel-session",
      Array.from({ length: 20 }, (_, index) => ({
        id: `call-${index}`,
        name: "parallel",
        arguments: { index },
      })),
      async (event) => {
        events.push(event);
      },
      "turn",
      TURN,
    );

    expect(peak).toBe(4);
    expect(results.map((result) => result.id)).toEqual(
      Array.from({ length: 20 }, (_, index) => `call-${index}`),
    );
    expect(
      events
        .filter(
          (event) =>
            event.type === EventType.TOOL_CALL_COMPLETED ||
            event.type === EventType.TOOL_CALL_FAILED,
        )
        .map((event) => event.tool_call_id),
    ).toEqual(Array.from({ length: 20 }, (_, index) => `call-${index}`));
  });

  it("runs unmarked tools as exclusive sequential barriers", async () => {
    let active = 0;
    let peak = 0;
    const planner = new ToolPlanner({
      executor: async () => {
        active++;
        peak = Math.max(peak, active);
        await new Promise((resolve) => setTimeout(resolve, 1));
        active--;
        return { ok: true };
      },
      specs: new Map([["unsafe", spec("unsafe")]]),
    });
    await planner.executeBatch(
      "sequential-session",
      Array.from({ length: 6 }, (_, index) => ({
        id: `call-${index}`,
        name: "unsafe",
        arguments: {},
      })),
      async () => {},
      "turn",
      TURN,
    );
    expect(peak).toBe(1);
  });

  it("reports queue cancellation before start", async () => {
    const controller = new ToolExecutionController({
      limits: { maxParallel: 1, timeoutMs: null },
    });
    const blocker = deferred();
    const first = controller.execute({
      name: "first",
      args: {},
      context: context("queue", "first"),
      exclusive: false,
      onStarted: async () => {},
      execute: async () => blocker.promise,
    });
    await Promise.resolve();
    const abort = new AbortController();
    const started = vi.fn();
    const queued = controller.execute({
      name: "second",
      args: {},
      context: context("queue", "second", abort.signal),
      exclusive: false,
      onStarted: started,
      execute: async () => ({ ok: true }),
    });
    abort.abort();
    await expect(queued).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_CANCELLED", outcome: "not_started", retryable: true },
    });
    expect(started).not.toHaveBeenCalled();
    blocker.resolve();
    await first;
  });

  it("releases the claim and permit when the started event cannot be recorded", async () => {
    const controller = new ToolExecutionController({
      limits: { maxParallel: 1, timeoutMs: null },
    });
    const execute = vi.fn().mockResolvedValue({ ok: true });
    const request = {
      name: "tool",
      args: {},
      context: context("started-failure", "call"),
      exclusive: false,
      execute,
    } as const;
    await expect(
      controller.execute({
        ...request,
        onStarted: async () => {
          throw new Error("journal failed");
        },
      }),
    ).rejects.toThrow("journal failed");
    expect(execute).not.toHaveBeenCalled();
    await expect(
      controller.execute({ ...request, onStarted: async () => {} }),
    ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
    expect(execute).toHaveBeenCalledOnce();
  });

  it("publishes a sanitized start-record failure to waiters while rethrowing the journal cause", async () => {
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    const startEntered = deferred();
    const startGate = deferred();
    const journalCause = new Error("private journal storage detail");
    const execute = vi.fn().mockResolvedValue({ ok: true });
    const request = {
      name: "start-record",
      args: {},
      context: context("start-record", "call"),
      exclusive: false,
      onStarted: async () => {
        startEntered.resolve();
        await startGate.promise;
        throw journalCause;
      },
      execute,
    } as const;
    const owner = controller.execute(request);
    await startEntered.promise;
    const waiter = controller.execute(request);
    const ownerRejected = expect(owner).rejects.toBe(journalCause);
    startGate.resolve();
    await ownerRejected;
    await expect(waiter).resolves.toMatchObject({
      status: "failed",
      error: {
        message: "Tool execution did not start",
        error_code: "TOOL_START_RECORD_FAILED",
        retryable: true,
        outcome: "not_started",
      },
    });
    expect(JSON.stringify(await waiter)).not.toContain("private journal storage detail");
    expect(execute).not.toHaveBeenCalled();

    await expect(
      controller.execute({ ...request, onStarted: async () => {} }),
    ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
    expect(execute).toHaveBeenCalledOnce();
  });

  it.each(["timeout", "cancel"] as const)(
    "does not invoke the handler when a slow start append crosses %s",
    async (mode) => {
      const abort = new AbortController();
      const controller = new ToolExecutionController({
        limits: { timeoutMs: mode === "timeout" ? 5 : null },
      });
      const startEntered = deferred();
      const startGate = deferred();
      const execute = vi.fn().mockResolvedValue({ ok: true });
      const request = {
        name: "slow-start",
        args: {},
        context: context(`slow-start-${mode}`, "call", abort.signal),
        exclusive: false,
        onStarted: async () => {
          startEntered.resolve();
          await startGate.promise;
        },
        execute,
      };
      const pending = controller.execute(request);
      await startEntered.promise;
      if (mode === "cancel") abort.abort();
      else await new Promise((resolve) => setTimeout(resolve, 10));
      startGate.resolve();
      await expect(pending).resolves.toMatchObject({
        status: "failed",
        error: {
          error_code: mode === "cancel" ? "TOOL_CANCELLED" : "TOOL_TIMEOUT",
          retryable: true,
          outcome: "not_started",
        },
      });
      expect(execute).not.toHaveBeenCalled();

      await expect(
        controller.execute({
          ...request,
          context: context(`slow-start-${mode}`, "call"),
          onStarted: async () => {},
        }),
      ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
      expect(execute).toHaveBeenCalledOnce();
    },
  );

  it("rejects malformed context before claim, permit, start, or handler", async () => {
    const ledger = new InMemoryToolIdempotencyLedger();
    const claim = vi.spyOn(ledger, "claim");
    const controller = new ToolExecutionController({
      limits: { maxParallel: 1, timeoutMs: null },
      ledger,
    });
    const onStarted = vi.fn();
    const execute = vi.fn().mockResolvedValue({ ok: true });
    const fingerprintTouched = vi.fn();
    const invalidArgs: Record<string, unknown> = {};
    Object.defineProperty(invalidArgs, "private", {
      enumerable: true,
      get() {
        fingerprintTouched();
        return "value";
      },
    });
    const invalidContext = {
      ...context("invalid-context", "call"),
      idempotencyKey: "mismatched-private-value",
    };
    await expect(
      controller.execute({
        name: "tool",
        args: invalidArgs,
        context: invalidContext,
        exclusive: false,
        onStarted,
        execute,
      }),
    ).rejects.toThrow(new TypeError("Invalid tool execution context"));
    expect(claim).not.toHaveBeenCalled();
    expect(fingerprintTouched).not.toHaveBeenCalled();
    expect(onStarted).not.toHaveBeenCalled();
    expect(execute).not.toHaveBeenCalled();
    expect(await controller.drain(0)).toEqual([]);

    await expect(
      controller.execute({
        name: "tool",
        args: {},
        context: context("invalid-context", "call"),
        exclusive: false,
        onStarted,
        execute,
      }),
    ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
    expect(claim).toHaveBeenCalledOnce();
    expect(onStarted).toHaveBeenCalledOnce();
    expect(execute).toHaveBeenCalledOnce();
  });

  it("never writes a fallback failed terminal after a completed append fails", async () => {
    const planner = new ToolPlanner({
      executor: async () => ({ ok: true }),
      specs: new Map([["tool", spec("tool")]]),
    });
    const events: string[] = [];
    await expect(
      planner.executeBatch(
        "terminal-failure",
        [{ id: "call", name: "tool", arguments: {} }],
        async (event) => {
          events.push(event.type);
          if (event.type === EventType.TOOL_CALL_COMPLETED) throw new Error("ambiguous append");
        },
        "turn",
        TURN,
      ),
    ).rejects.toBeInstanceOf(AggregateError);
    expect(events.filter((type) => type === EventType.TOOL_CALL_COMPLETED)).toHaveLength(1);
    expect(events).not.toContain(EventType.TOOL_CALL_FAILED);
  });

  it("retains permits and drain visibility for non-cooperative timed-out work", async () => {
    const controller = new ToolExecutionController({
      limits: { maxParallel: 4, timeoutMs: 5 },
    });
    const gates = Array.from({ length: 4 }, () => deferred());
    const running = gates.map((gate, index) =>
      controller.execute({
        name: "stuck",
        args: { index },
        context: context("stuck-session", `stuck-${index}`),
        exclusive: false,
        onStarted: async () => {},
        execute: async () => gate.promise,
      }),
    );
    await expect(Promise.all(running)).resolves.toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          status: "failed",
          error: expect.objectContaining({ error_code: "TOOL_TIMEOUT", outcome: "unknown" }),
        }),
      ]),
    );
    expect(await controller.drain(0)).toEqual(["stuck-0", "stuck-1", "stuck-2", "stuck-3"]);

    const fifthStarted = vi.fn();
    await expect(
      controller.execute({
        name: "fifth",
        args: {},
        context: context("stuck-session", "fifth"),
        exclusive: false,
        onStarted: fifthStarted,
        execute: async () => ({ ok: true }),
      }),
    ).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_TIMEOUT", outcome: "not_started" },
    });
    expect(fifthStarted).not.toHaveBeenCalled();

    gates.forEach((gate) => gate.resolve());
    expect(await controller.drain(50)).toEqual([]);
  });

  it("cancels a cooperative running sibling and a queued sibling with one terminal each", async () => {
    const controller = new ToolExecutionController({
      limits: { maxParallel: 1, timeoutMs: null },
    });
    const tool = spec("cooperative", { parallel_safe: true });
    const parent = new AbortController();
    const started = deferred();
    const planner = new ToolPlanner({
      executionController: controller,
      specs: new Map([[tool.name, tool]]),
      executor: async (_name, _args, executionContext) => {
        started.resolve();
        await new Promise<void>((_resolve, reject) => {
          executionContext.signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      },
    });
    const events: Array<{ type: string; tool_call_id?: string }> = [];
    const pending = planner.executeBatch(
      "parent-cancel",
      [
        { id: "running", name: "cooperative", arguments: {} },
        { id: "queued", name: "cooperative", arguments: {} },
      ],
      async (event) => {
        events.push(event);
      },
      "turn",
      TURN,
      parent.signal,
    );
    await started.promise;
    parent.abort();
    const results = await pending;
    expect(results).toEqual([
      expect.objectContaining({ error_code: "TOOL_CANCELLED", outcome: "unknown" }),
      expect.objectContaining({ error_code: "TOOL_CANCELLED", outcome: "not_started" }),
    ]);
    for (const id of ["running", "queued"]) {
      expect(
        events.filter(
          (event) =>
            event.tool_call_id === id &&
            (event.type === EventType.TOOL_CALL_COMPLETED ||
              event.type === EventType.TOOL_CALL_FAILED),
        ),
      ).toHaveLength(1);
    }
  });

  it("coalesces an exact call identity but executes different call IDs", async () => {
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    const gate = deferred();
    const execute = vi.fn(async () => {
      await gate.promise;
      return { nested: { value: 1 } };
    });
    const request = (callId: string) =>
      controller.execute({
        name: "same",
        args: { value: 1 },
        context: context("identity", callId),
        exclusive: false,
        onStarted: async () => {},
        execute,
      });
    const first = request("shared");
    const duplicateA = request("shared");
    const duplicateB = request("shared");
    const duplicateC = request("shared");
    gate.resolve();
    const [owner, waiterA, waiterB, waiterC] = await Promise.all([
      first,
      duplicateA,
      duplicateB,
      duplicateC,
    ]);
    expect(execute).toHaveBeenCalledOnce();
    expect(owner).toEqual(waiterA);
    expect(new Set([owner, waiterA, waiterB, waiterC]).size).toBe(4);
    const resultA = (waiterA as { result: { nested: { value: number } } }).result;
    const resultB = (waiterB as { result: { nested: { value: number } } }).result;
    const resultC = (waiterC as { result: { nested: { value: number } } }).result;
    expect(Object.isFrozen(resultA)).toBe(true);
    expect(Object.isFrozen(resultA.nested)).toBe(true);
    expect(resultB.nested.value).toBe(1);
    expect(resultC.nested.value).toBe(1);
    expect(resultA).not.toBe(resultB);
    expect(resultA.nested).not.toBe(resultB.nested);
    await request("different");
    expect(execute).toHaveBeenCalledTimes(2);
  });

  it("lets running-claim waiters cancel or expire without cancelling the owner", async () => {
    const controller = new ToolExecutionController({ limits: { timeoutMs: null } });
    const gate = deferred();
    const ownerStarted = deferred();
    const execute = vi.fn(async () => {
      ownerStarted.resolve();
      await gate.promise;
      return { ok: true };
    });
    const owner = controller.execute({
      name: "shared",
      args: {},
      context: context("waiters", "shared"),
      exclusive: false,
      onStarted: async () => {},
      execute,
    });
    await ownerStarted.promise;
    const cancelled = new AbortController();
    const cancelledWaiter = controller.execute({
      name: "shared",
      args: {},
      context: context("waiters", "shared", cancelled.signal),
      exclusive: false,
      onStarted: async () => {},
      execute,
    });
    const expiredWaiter = controller.execute({
      name: "shared",
      args: {},
      context: { ...context("waiters", "shared"), deadlineMs: Date.now() + 50 },
      exclusive: false,
      onStarted: async () => {},
      execute,
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    cancelled.abort();
    await expect(cancelledWaiter).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_CANCELLED", outcome: "unknown" },
    });
    await expect(expiredWaiter).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_TIMEOUT", outcome: "unknown" },
    });
    expect(execute).toHaveBeenCalledOnce();
    gate.resolve();
    await expect(owner).resolves.toMatchObject({ status: "completed", result: { ok: true } });
    await expect(
      controller.execute({
        name: "shared",
        args: {},
        context: context("waiters", "shared"),
        exclusive: false,
        onStarted: async () => {},
        execute,
      }),
    ).resolves.toMatchObject({ status: "completed", result: { ok: true } });
    expect(execute).toHaveBeenCalledOnce();
  });

  it("tombstones ambiguous failures and re-executes only typed retryable failures", async () => {
    const ambiguous = new ToolExecutionController({ limits: { timeoutMs: null } });
    const ambiguousExecute = vi.fn(async () => {
      throw new Error("secret arbitrary failure");
    });
    const ambiguousRequest = {
      name: "ambiguous",
      args: {},
      context: context("certainty", "ambiguous"),
      exclusive: false,
      onStarted: async () => {},
      execute: ambiguousExecute,
    } as const;
    const first = await ambiguous.execute(ambiguousRequest);
    const replay = await ambiguous.execute(ambiguousRequest);
    expect(first).toMatchObject({ status: "failed", error: { outcome: "unknown" } });
    expect(JSON.stringify(first)).not.toContain("secret arbitrary failure");
    expect(replay).toMatchObject({ status: "failed", error: { outcome: "unknown" } });
    expect(ambiguousExecute).toHaveBeenCalledOnce();

    const retryable = new ToolExecutionController({ limits: { timeoutMs: null } });
    const retryableExecute = vi
      .fn()
      .mockRejectedValueOnce(
        new ToolExecutionError("secret typed failure", "TOOL_EXECUTION_FAILED", true, "failed"),
      )
      .mockResolvedValueOnce({ ok: true });
    const retryableRequest = {
      ...ambiguousRequest,
      name: "retryable",
      context: context("certainty", "retryable"),
      execute: retryableExecute,
    };
    await expect(retryable.execute(retryableRequest)).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_EXECUTION_FAILED", retryable: true, outcome: "failed" },
    });
    await expect(retryable.execute(retryableRequest)).resolves.toMatchObject({
      status: "completed",
      result: { ok: true },
    });
    expect(retryableExecute).toHaveBeenCalledTimes(2);

    const notStarted = new ToolExecutionController({ limits: { timeoutMs: null } });
    const notStartedExecute = vi.fn(async () => {
      throw new ToolExecutionError("secret", "NOT_STARTED_BUT_TOO_LATE", true, "not_started");
    });
    const notStartedRequest = {
      ...ambiguousRequest,
      name: "late-not-started",
      context: context("certainty", "late-not-started"),
      execute: notStartedExecute,
    };
    await expect(notStarted.execute(notStartedRequest)).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_EXECUTION_FAILED", retryable: false, outcome: "unknown" },
    });
    await notStarted.execute(notStartedRequest);
    expect(notStartedExecute).toHaveBeenCalledOnce();
  });

  it("aborts a cooperative handler on timeout and releases its permit on settlement", async () => {
    const controller = new ToolExecutionController({ limits: { timeoutMs: 5 } });
    let observedAbort = false;
    const outcome = await controller.execute({
      name: "cooperative-timeout",
      args: {},
      context: context("cooperative-timeout", "call"),
      exclusive: false,
      onStarted: async () => {},
      execute: async (executionContext) =>
        new Promise((_resolve, reject) => {
          executionContext.signal.addEventListener(
            "abort",
            () => {
              observedAbort = executionContext.signal.aborted;
              reject(new DOMException("aborted", "AbortError"));
            },
            { once: true },
          );
        }),
    });
    expect(outcome).toMatchObject({
      status: "failed",
      error: { error_code: "TOOL_TIMEOUT", outcome: "unknown" },
    });
    expect(observedAbort).toBe(true);
    expect(await controller.drain(50)).toEqual([]);
  });

  it("rejects capacity before onStarted when only an unknown tombstone remains", async () => {
    const ledger = new InMemoryToolIdempotencyLedger({ capacity: 1 });
    const occupied = await ledger.claim("capacity", "occupied", "occupied");
    expect(occupied.status).toBe("owner");
    if (occupied.status !== "owner") return;
    await ledger.unknownOutcome(occupied.claim, toolTimedOut("unknown"));
    const controller = new ToolExecutionController({ ledger });
    const onStarted = vi.fn();
    await expect(
      controller.execute({
        name: "new",
        args: {},
        context: context("capacity", "new"),
        exclusive: false,
        onStarted,
        execute: async () => ({ ok: true }),
      }),
    ).resolves.toMatchObject({
      status: "failed",
      error: { error_code: "IDEMPOTENCY_CAPACITY_EXCEEDED", outcome: "not_started" },
    });
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("tracks the same call ID independently across sessions", async () => {
    const controller = new ToolExecutionController({ limits: { timeoutMs: 5 } });
    const gates = [deferred(), deferred()];
    await Promise.all(
      gates.map((gate, index) =>
        controller.execute({
          name: "stuck",
          args: {},
          context: context(`session-${index}`, "same-call"),
          exclusive: false,
          onStarted: async () => {},
          execute: async () => gate.promise,
        }),
      ),
    );
    expect(await controller.drain(0)).toEqual(["same-call", "same-call"]);
    gates.forEach((gate) => gate.resolve());
    await controller.drain(50);
  });

  it("keeps a timed-out unsafe barrier exclusive until actual settlement", async () => {
    const gate = deferred();
    const safeStarted = vi.fn();
    const specs = new Map<string, ToolSpec>([
      ["barrier", spec("barrier", { timeout_ms: 5, risk: "external_effect" })],
      ["safe", spec("safe", { parallel_safe: true, timeout_ms: 10 })],
    ]);
    const planner = new ToolPlanner({
      specs,
      executionLimits: { timeoutMs: null },
      executor: async (name) => {
        if (name === "barrier") await gate.promise;
        else safeStarted();
        return { ok: true };
      },
    });
    const result = await planner.executeBatch(
      "barrier-session",
      [
        { id: "barrier", name: "barrier", arguments: {} },
        { id: "safe", name: "safe", arguments: {} },
      ],
      async () => {},
      "turn",
      TURN,
    );
    expect(result).toEqual([
      expect.objectContaining({ error_code: "TOOL_TIMEOUT", outcome: "unknown" }),
      expect.objectContaining({ error_code: "TOOL_TIMEOUT", outcome: "not_started" }),
    ]);
    expect(safeStarted).not.toHaveBeenCalled();
    gate.resolve();
    await planner.executionController.drain(50);
  });

  it("emits exactly one terminal for every accepted request across the fault matrix", async () => {
    const cases: Array<{
      id: string;
      planner: ToolPlanner;
      args?: Record<string, unknown>;
      signal?: AbortSignal;
      cleanup?: () => Promise<void>;
    }> = [];
    cases.push({
      id: "success",
      planner: new ToolPlanner({
        specs: new Map([["tool", spec("tool")]]),
        executor: async () => ({ ok: true }),
      }),
    });
    cases.push({
      id: "exception",
      planner: new ToolPlanner({
        specs: new Map([["tool", spec("tool")]]),
        executor: async () => {
          throw new Error("private failure");
        },
      }),
    });
    cases.push({
      id: "validation",
      args: {},
      planner: new ToolPlanner({
        specs: new Map([
          [
            "tool",
            spec("tool", {
              parameters: {
                type: "object",
                properties: { required: { type: "string" } },
                required: ["required"],
              },
            }),
          ],
        ]),
        executor: async () => ({ ok: true }),
      }),
    });
    const cancelled = new AbortController();
    cancelled.abort();
    cases.push({
      id: "cancelled",
      signal: cancelled.signal,
      planner: new ToolPlanner({
        specs: new Map([["tool", spec("tool")]]),
        executor: async () => ({ ok: true }),
      }),
    });
    const timeoutGate = deferred();
    const timeoutPlanner = new ToolPlanner({
      executionLimits: { timeoutMs: 5 },
      specs: new Map([["tool", spec("tool", { parallel_safe: true })]]),
      executor: async () => timeoutGate.promise,
    });
    cases.push({
      id: "timeout",
      planner: timeoutPlanner,
      cleanup: async () => {
        timeoutGate.resolve();
        await timeoutPlanner.executionController.drain(50);
      },
    });
    const capacityLedger = new InMemoryToolIdempotencyLedger({ capacity: 1 });
    const occupied = await capacityLedger.claim("occupied", "call", "occupied");
    expect(occupied.status).toBe("owner");
    if (occupied.status !== "owner") return;
    await capacityLedger.unknownOutcome(occupied.claim, toolTimedOut("unknown"));
    cases.push({
      id: "capacity",
      planner: new ToolPlanner({
        executionController: new ToolExecutionController({ ledger: capacityLedger }),
        specs: new Map([["tool", spec("tool")]]),
        executor: async () => ({ ok: true }),
      }),
    });
    cases.push({
      id: "policy-denied",
      planner: new ToolPlanner({
        policy: new ToolPolicy({ denied: new Set(["tool"]) }),
        specs: new Map([["tool", spec("tool")]]),
        executor: async () => ({ ok: true }),
      }),
    });
    cases.push({
      id: "approval-rejected",
      planner: new ToolPlanner({
        policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
        approvalHandler: async () => false,
        specs: new Map([["tool", spec("tool", { risk: "destructive" })]]),
        executor: async () => ({ ok: true }),
      }),
    });

    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      for (const testCase of cases) {
        const events: Array<{ type: string; tool_call_id?: string }> = [];
        let sequence = 0;
        await testCase.planner.executeBatch(
          `matrix-${testCase.id}`,
          [{ id: testCase.id, name: "tool", arguments: testCase.args ?? {} }],
          async (event) => {
            events.push(event);
            return StoredKajiEvent.parse({ ...event, sequence: ++sequence });
          },
          "turn",
          TURN,
          testCase.signal,
        );
        expect(
          events.filter((event) => event.type === EventType.TOOL_CALL_REQUESTED),
          testCase.id,
        ).toHaveLength(1);
        expect(
          events.filter(
            (event) =>
              event.type === EventType.TOOL_CALL_COMPLETED ||
              event.type === EventType.TOOL_CALL_FAILED,
          ),
          testCase.id,
        ).toHaveLength(1);
        await testCase.cleanup?.();
      }
    } finally {
      logged.mockRestore();
    }
  });
});
