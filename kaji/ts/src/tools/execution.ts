import { snapshotToolExecutionContext, type ToolExecutionContext } from "@/runtime/context";
import { DurableJsonLimitError, InvalidDurableValueError } from "@/events/errors";
import { durableJsonSnapshot } from "@/events/json";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/schemas";
import { logRedactedFailure } from "@/internal/safe-logging";
import { systemTimerScheduler, type TimerHandle, type TimerScheduler } from "@/internal/uuid";
import {
  NOOP_METRICS,
  NOOP_TRACE,
  recordMetric,
  startSpan,
  type MetricsSink,
  type ToolMetricOutcome,
  type TraceSink,
} from "@/observability";
import {
  ToolExecutionError,
  durableToolResultTombstone,
  invalidToolResult,
  normalizeStartedToolFailure,
  publicToolExecutionError,
  snapshotToolExecutionError,
  toolCancelled,
  toolExecutionUnknown,
  toolStartRecordFailed,
  toolTimedOut,
} from "@/tools/execution-errors";
import {
  InMemoryToolIdempotencyLedger,
  type ToolClaimResult,
  type ToolIdempotencyLedger,
  type ToolLedgerOutcome,
} from "@/tools/idempotency";

export interface ToolExecutionLimits {
  readonly maxParallel: number;
  readonly timeoutMs: number | null;
  readonly approvalTimeoutMs: number;
}

export const DEFAULT_TOOL_EXECUTION_LIMITS: Readonly<ToolExecutionLimits> = Object.freeze({
  maxParallel: 4,
  timeoutMs: 30_000,
  approvalTimeoutMs: 300_000,
});

export type ToolExecutionControllerOutcome =
  | { readonly status: "completed"; readonly result: unknown }
  | {
      readonly status: "failed";
      readonly error: ToolExecutionError;
      /** True only for a deadline observed by this invocation, never a ledger replay. */
      readonly turnTimeout?: true;
    };

export interface ToolExecutionRequest {
  readonly name: string;
  readonly args: Readonly<Record<string, unknown>>;
  readonly context: ToolExecutionContext;
  readonly timeoutMs?: number;
  readonly exclusive: boolean;
  /**
   * Persist the start acknowledgement and settle when the append is no longer active.
   * Implementations must observe `signal`; otherwise the claim and permit remain owned,
   * `drain()` reports the call, and the process must be restarted if it never settles.
   */
  readonly onStarted: (signal: AbortSignal) => Promise<void>;
  readonly execute: (context: ToolExecutionContext) => Promise<unknown>;
}

export interface ToolExecutionControllerOptions {
  limits?: Partial<ToolExecutionLimits>;
  ledger?: ToolIdempotencyLedger;
  now?: () => number;
  monotonicNow?: () => number;
  timerScheduler?: TimerScheduler;
  metricsSink?: MetricsSink;
  traceSink?: TraceSink;
}

interface PermitWaiter {
  readonly count: number;
  readonly signal: AbortSignal;
  readonly resolve: (release: () => void) => void;
  readonly reject: (reason: unknown) => void;
  readonly onAbort: () => void;
}

class PermitPool {
  private available: number;
  private readonly queue: PermitWaiter[] = [];

  constructor(size: number) {
    this.available = size;
  }

  acquire(signal: AbortSignal, count = 1): Promise<() => void> {
    if (signal.aborted) return Promise.reject(signal.reason);
    if (this.queue.length === 0 && this.available >= count) {
      this.available -= count;
      return Promise.resolve(this.releaseOnce(count));
    }
    return new Promise((resolve, reject) => {
      const waiter: PermitWaiter = {
        count,
        signal,
        resolve,
        reject,
        onAbort: () => {
          const index = this.queue.indexOf(waiter);
          if (index >= 0) this.queue.splice(index, 1);
          reject(signal.reason);
          this.dispatch();
        },
      };
      signal.addEventListener("abort", waiter.onAbort, { once: true });
      this.queue.push(waiter);
    });
  }

  private releaseOnce(count: number): () => void {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.available += count;
      this.dispatch();
    };
  }

  private dispatch(): void {
    while (this.queue.length > 0) {
      const waiter = this.queue[0]!;
      if (waiter.signal.aborted) {
        this.queue.shift();
        waiter.signal.removeEventListener("abort", waiter.onAbort);
        continue;
      }
      if (this.available < waiter.count) return;
      this.queue.shift();
      waiter.signal.removeEventListener("abort", waiter.onAbort);
      this.available -= waiter.count;
      waiter.resolve(this.releaseOnce(waiter.count));
    }
  }
}

type AbortKind = "cancelled" | "tool_timeout" | "turn_timeout";

interface LinkedSignal {
  readonly signal: AbortSignal;
  readonly deadlineMonotonicMs: number | undefined;
  readonly kind: () => AbortKind | undefined;
  readonly cleanup: () => void;
}

function validateLimits(limits: ToolExecutionLimits): void {
  if (!Number.isInteger(limits.maxParallel) || limits.maxParallel < 1) {
    throw new RangeError("maxParallel must be a positive integer");
  }
  if (limits.timeoutMs !== null && (!Number.isInteger(limits.timeoutMs) || limits.timeoutMs < 1)) {
    throw new RangeError("timeoutMs must be a positive integer or null");
  }
  if (!Number.isInteger(limits.approvalTimeoutMs) || limits.approvalTimeoutMs < 1) {
    throw new RangeError("approvalTimeoutMs must be a positive integer");
  }
}

function invocationFingerprint(name: string, args: Readonly<Record<string, unknown>>): string {
  const stable = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(stable);
    if (value !== null && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value as Record<string, unknown>)
          .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
          .map(([key, item]) => [key, stable(item)]),
      );
    }
    return value;
  };
  return JSON.stringify([name, stable(args)]);
}

function fromLedger(outcome: ToolLedgerOutcome): ToolExecutionControllerOutcome {
  if (outcome.status === "failed") {
    return { status: "failed", error: publicToolExecutionError(outcome.error) };
  }
  try {
    return {
      status: "completed",
      result: durableJsonSnapshot(outcome.result, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES),
    };
  } catch (error) {
    if (error instanceof InvalidDurableValueError || error instanceof DurableJsonLimitError) {
      return { status: "failed", error: invalidToolResult() };
    }
    throw error;
  }
}

function snapshotExecutionRequestContext(context: unknown): ToolExecutionContext {
  try {
    return Object.freeze(snapshotToolExecutionContext(context as ToolExecutionContext));
  } catch (cause) {
    throw new TypeError("Invalid tool execution context", { cause });
  }
}

class ToolStartRecordingError extends Error {
  constructor(
    readonly failure: ToolExecutionError,
    readonly original: unknown,
  ) {
    super("Tool start recording failed", { cause: original });
    this.name = "ToolStartRecordingError";
  }
}

function toolMetricFields(outcome: ToolExecutionControllerOutcome): {
  outcome: ToolMetricOutcome;
  error_code: string;
} {
  if (outcome.status === "completed") return { outcome: "completed", error_code: "NONE" };
  const metricOutcome: ToolMetricOutcome =
    outcome.error.error_code === "TOOL_TIMEOUT" || outcome.error.error_code === "TURN_TIMEOUT"
      ? "timeout"
      : outcome.error.error_code === "TOOL_CANCELLED"
        ? "cancelled"
        : outcome.error.outcome;
  return { outcome: metricOutcome, error_code: outcome.error.error_code };
}

/** Runtime-lifetime bounded tool execution and idempotency controller. */
export class ToolExecutionController {
  readonly limits: Readonly<ToolExecutionLimits>;
  readonly ledger: ToolIdempotencyLedger;
  private readonly permits: PermitPool;
  private readonly monotonicNow: () => number;
  private readonly timerScheduler: TimerScheduler;
  private readonly metrics: MetricsSink;
  private readonly trace: TraceSink;
  private readonly active = new Map<
    string,
    { sessionId: string; callId: string; settled: Promise<void> }
  >();
  private readonly pendingStarts = new Map<
    string,
    { sessionId: string; callId: string; settled: Promise<void>; resolve: () => void }
  >();
  private readonly claimCleanups = new Set<{
    sessionId: string;
    callId: string;
    settled: Promise<void>;
  }>();

  constructor(options: ToolExecutionControllerOptions = {}) {
    this.limits = Object.freeze({ ...DEFAULT_TOOL_EXECUTION_LIMITS, ...options.limits });
    validateLimits(this.limits);
    this.ledger = options.ledger ?? new InMemoryToolIdempotencyLedger();
    this.permits = new PermitPool(this.limits.maxParallel);
    this.monotonicNow = options.monotonicNow ?? (() => globalThis.performance.now());
    this.timerScheduler = options.timerScheduler ?? systemTimerScheduler;
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.trace = options.traceSink ?? NOOP_TRACE;
  }

  async execute(request: ToolExecutionRequest): Promise<ToolExecutionControllerOutcome> {
    const canonicalContext = snapshotExecutionRequestContext(request.context);
    const started = this.monotonicNow();
    const span = startSpan(this.trace, "kaji.tool", {
      "session.id": canonicalContext.sessionId,
      "turn.id": canonicalContext.turnId,
      "request.id": canonicalContext.requestId,
      "trace.id": canonicalContext.traceId,
      "tool.call_id": canonicalContext.toolCallId,
    });
    try {
      const outcome = await this.executeBounded(request, canonicalContext);
      if (outcome.status === "failed") span.recordError(outcome.error);
      recordMetric(
        this.metrics,
        "kaji.tool.duration_ms",
        Math.max(0, this.monotonicNow() - started),
        toolMetricFields(outcome),
      );
      return outcome;
    } catch (error) {
      const observed =
        error instanceof ToolStartRecordingError
          ? ({ status: "failed", error: error.failure } as const)
          : undefined;
      span.recordError(error instanceof ToolStartRecordingError ? error.original : error);
      recordMetric(
        this.metrics,
        "kaji.tool.duration_ms",
        Math.max(0, this.monotonicNow() - started),
        observed === undefined
          ? { outcome: "failed", error_code: "OTHER" }
          : toolMetricFields(observed),
      );
      if (error instanceof ToolStartRecordingError) throw error.original;
      throw error;
    } finally {
      span.end();
    }
  }

  private async executeBounded(
    request: ToolExecutionRequest,
    canonicalContext: ToolExecutionContext,
  ): Promise<ToolExecutionControllerOutcome> {
    const queueStarted = this.monotonicNow();
    const key = JSON.stringify([canonicalContext.sessionId, canonicalContext.toolCallId]);
    const linked = this.linkedSignal(canonicalContext, request.timeoutMs);
    let fingerprint: string;
    try {
      fingerprint = invocationFingerprint(request.name, request.args);
    } catch (error) {
      linked.cleanup();
      throw error;
    }
    const claimPromise = Promise.resolve().then(() =>
      this.ledger.claim(canonicalContext.sessionId, canonicalContext.toolCallId, fingerprint),
    );
    let removeClaimAbortListener = () => {};
    const claimAborted = new Promise<{ readonly status: "aborted" }>((resolve) => {
      const finish = () => resolve({ status: "aborted" });
      if (linked.signal.aborted) finish();
      else {
        linked.signal.addEventListener("abort", finish, { once: true });
        removeClaimAbortListener = () => linked.signal.removeEventListener("abort", finish);
      }
    });
    const claimed = await Promise.race([
      claimPromise.then(
        (claim) => ({ status: "claimed" as const, claim }),
        (error: unknown) => ({ status: "failed" as const, error }),
      ),
      claimAborted,
    ]);
    removeClaimAbortListener();
    if (claimed.status === "aborted") {
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      const error = outcome.error;
      this.scheduleLateClaimCleanup(
        canonicalContext.sessionId,
        canonicalContext.toolCallId,
        claimPromise,
        error,
      );
      linked.cleanup();
      return outcome;
    }
    if (claimed.status === "failed") {
      linked.cleanup();
      if (claimed.error instanceof ToolExecutionError) {
        return { status: "failed", error: claimed.error };
      }
      throw claimed.error;
    }
    const claimResult = claimed.claim;
    if (linked.signal.aborted) {
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      const error = outcome.error;
      if (claimResult.status === "owner") {
        await this.ledger.retryableFailure(claimResult.claim, error);
      }
      linked.cleanup();
      return outcome;
    }
    if (claimResult.status === "running") {
      return this.waitForRunningOutcome(claimResult.outcome, linked);
    }
    if (claimResult.status === "completed") {
      linked.cleanup();
      return fromLedger({ status: "completed", result: claimResult.result });
    }
    if (claimResult.status === "unknown") {
      linked.cleanup();
      return { status: "failed", error: publicToolExecutionError(claimResult.error) };
    }

    const claim = claimResult.claim;
    let release: (() => void) | undefined;
    try {
      release = await this.permits.acquire(
        linked.signal,
        request.exclusive ? this.limits.maxParallel : 1,
      );
    } catch {
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      const error = outcome.error;
      recordMetric(
        this.metrics,
        "kaji.tool.queue_wait_ms",
        Math.max(0, this.monotonicNow() - queueStarted),
        {
          outcome:
            error.error_code === "TOOL_TIMEOUT" || error.error_code === "TURN_TIMEOUT"
              ? "timeout"
              : "cancelled",
        },
      );
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      return outcome;
    }

    recordMetric(
      this.metrics,
      "kaji.tool.queue_wait_ms",
      Math.max(0, this.monotonicNow() - queueStarted),
      { outcome: "acquired" },
    );

    if (linked.signal.aborted) {
      release();
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      const error = outcome.error;
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      return outcome;
    }

    let removeStartAbortListener = () => {};
    const startAborted = new Promise<{ readonly status: "aborted" }>((resolve) => {
      const finish = () => resolve({ status: "aborted" });
      if (linked.signal.aborted) finish();
      else {
        linked.signal.addEventListener("abort", finish, { once: true });
        removeStartAbortListener = () => linked.signal.removeEventListener("abort", finish);
      }
    });
    let startOperation: Promise<void>;
    try {
      startOperation = Promise.resolve(request.onStarted(linked.signal));
    } catch (cause) {
      startOperation = Promise.reject(cause);
    }
    const start = this.trackPendingStart(
      key,
      canonicalContext.sessionId,
      canonicalContext.toolCallId,
      startOperation,
    );
    const startResult = start.then(
      () => ({ status: "started" as const }),
      (cause: unknown) => ({ status: "failed" as const, cause }),
    );
    const firstStartResult = await Promise.race([startResult, startAborted]);
    removeStartAbortListener();

    if (firstStartResult.status === "aborted") {
      // A start append is an acknowledgement boundary. Keep the claim and
      // permit owned until it physically settles so Failed cannot overtake a
      // late Started append from a non-cooperative committer.
      await startResult;
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      try {
        await this.ledger.retryableFailure(claim, outcome.error);
        return outcome;
      } finally {
        this.finishPendingStart(key);
        release();
        linked.cleanup();
      }
    }

    if (firstStartResult.status === "failed") {
      const error = toolStartRecordFailed(firstStartResult.cause);
      try {
        await this.ledger.retryableFailure(claim, error);
      } finally {
        this.finishPendingStart(key);
        release();
        linked.cleanup();
      }
      throw new ToolStartRecordingError(error, firstStartResult.cause);
    }

    if (linked.signal.aborted) {
      const outcome = this.abortOutcome(linked.kind(), "not_started");
      const error = outcome.error;
      try {
        await this.ledger.retryableFailure(claim, error);
        return outcome;
      } finally {
        this.finishPendingStart(key);
        release();
        linked.cleanup();
      }
    }

    const executionContext = snapshotToolExecutionContext({
      ...canonicalContext,
      signal: linked.signal,
      ...(linked.deadlineMonotonicMs === undefined
        ? {}
        : { deadlineMonotonicMs: linked.deadlineMonotonicMs }),
    });
    const settled = Promise.resolve()
      .then(() => request.execute(executionContext))
      .then<ToolExecutionControllerOutcome, ToolExecutionControllerOutcome>(
        (result) => ({ status: "completed", result }),
        (cause) => {
          logRedactedFailure("internal error", cause);
          return { status: "failed", error: normalizeStartedToolFailure(cause) };
        },
      );
    let removeAbortListener = () => {};
    const tracked = settled
      .then(() => undefined)
      .finally(() => {
        release!();
        linked.cleanup();
        removeAbortListener();
        this.active.delete(key);
        recordMetric(this.metrics, "kaji.tool.active", this.active.size, {});
      });
    this.active.set(key, {
      sessionId: canonicalContext.sessionId,
      callId: canonicalContext.toolCallId,
      settled: tracked,
    });
    this.finishPendingStart(key);
    recordMetric(this.metrics, "kaji.tool.active", this.active.size, {});

    const abort = new Promise<ToolExecutionControllerOutcome>((resolve) => {
      const finish = () => {
        resolve(this.abortOutcome(linked.kind(), "unknown"));
      };
      if (linked.signal.aborted) finish();
      else {
        linked.signal.addEventListener("abort", finish, { once: true });
        removeAbortListener = () => linked.signal.removeEventListener("abort", finish);
      }
    });
    const outcome = await Promise.race([settled, abort]);
    if (outcome.status === "completed") {
      let snapshot;
      try {
        snapshot = durableJsonSnapshot(
          outcome.result,
          "tool_result",
          MAX_DURABLE_TOOL_RESULT_BYTES,
        );
      } catch (cause) {
        if (cause instanceof InvalidDurableValueError || cause instanceof DurableJsonLimitError) {
          const error = invalidToolResult();
          await this.ledger.unknownOutcome(claim, durableToolResultTombstone(cause));
          return { status: "failed", error };
        }
        throw cause;
      }
      try {
        await this.ledger.complete(claim, snapshot);
        return { status: "completed", result: snapshot };
      } catch (cause) {
        const error = toolExecutionUnknown(cause);
        await this.ledger.unknownOutcome(claim, error);
        const failure = { status: "failed" as const, error };
        return failure;
      }
    }
    if (outcome.error.outcome === "failed") {
      await this.ledger.retryableFailure(claim, outcome.error);
    } else {
      await this.ledger.unknownOutcome(claim, outcome.error);
    }
    return outcome;
  }

  /** Wait for real start/handler settlement; report calls still owned at the deadline. */
  async drain(timeoutMs: number): Promise<readonly string[]> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
      throw new RangeError("timeoutMs must be a finite non-negative number");
    }
    const deadline = this.monotonicNow() + timeoutMs;
    let timer: TimerHandle | undefined;
    let expired = false;
    const timeout = new Promise<"expired">((resolve) => {
      timer = this.timerScheduler.schedule(Math.max(0, deadline - this.monotonicNow()), () => {
        expired = true;
        resolve("expired");
      });
    });
    try {
      while (this.active.size > 0 || this.pendingStarts.size > 0 || this.claimCleanups.size > 0) {
        const snapshot = [
          ...[...this.active.values()].map(({ settled }) => settled),
          ...[...this.pendingStarts.values()].map(({ settled }) => settled),
          ...[...this.claimCleanups].map(({ settled }) => settled),
        ];
        const wake = await Promise.race([
          Promise.allSettled(snapshot).then(() => "settled" as const),
          timeout,
        ]);
        if (wake === "expired" || expired) break;
        // Let a settled start synchronously hand ownership to the active map.
        await Promise.resolve();
      }
    } finally {
      timer?.cancel();
    }
    return [
      ...[...this.active.values()].map(({ callId }) => callId),
      ...[...this.pendingStarts.values()].map(({ callId }) => callId),
      ...[...this.claimCleanups].map(({ callId }) => callId),
    ].sort();
  }

  /** @internal Whether start recording or handler code still owns this session. */
  hasActiveSession(sessionId: string): boolean {
    return (
      [...this.active.values()].some((entry) => entry.sessionId === sessionId) ||
      [...this.pendingStarts.values()].some((entry) => entry.sessionId === sessionId) ||
      [...this.claimCleanups].some((entry) => entry.sessionId === sessionId)
    );
  }

  private trackPendingStart(
    key: string,
    sessionId: string,
    callId: string,
    operation: Promise<void>,
  ): Promise<void> {
    let resolve!: () => void;
    const settled = new Promise<void>((done) => {
      resolve = done;
    });
    this.pendingStarts.set(key, { sessionId, callId, settled, resolve });
    return operation;
  }

  private finishPendingStart(key: string): void {
    const pending = this.pendingStarts.get(key);
    if (pending === undefined) return;
    this.pendingStarts.delete(key);
    pending.resolve();
  }

  private abortOutcome(
    kind: AbortKind | undefined,
    outcome: "not_started" | "unknown",
  ): Extract<ToolExecutionControllerOutcome, { status: "failed" }> {
    if (kind === "turn_timeout") {
      return {
        status: "failed",
        error: new ToolExecutionError(
          "Agent turn timed out",
          "TURN_TIMEOUT",
          outcome === "not_started",
          outcome,
        ),
        turnTimeout: true,
      };
    }
    return {
      status: "failed",
      error: kind === "tool_timeout" ? toolTimedOut(outcome) : toolCancelled(outcome),
    };
  }

  private async waitForRunningOutcome(
    running: Promise<ToolLedgerOutcome>,
    linked: LinkedSignal,
  ): Promise<ToolExecutionControllerOutcome> {
    let removeAbortListener = () => {};
    try {
      const aborted = new Promise<ToolExecutionControllerOutcome>((resolve) => {
        const finish = () => {
          resolve(this.abortOutcome(linked.kind(), "unknown"));
        };
        if (linked.signal.aborted) finish();
        else {
          linked.signal.addEventListener("abort", finish, { once: true });
          removeAbortListener = () => linked.signal.removeEventListener("abort", finish);
        }
      });
      return await Promise.race([running.then(fromLedger), aborted]);
    } finally {
      removeAbortListener();
      linked.cleanup();
    }
  }

  private scheduleLateClaimCleanup(
    sessionId: string,
    callId: string,
    claimPromise: Promise<ToolClaimResult>,
    error: ToolExecutionError,
  ): void {
    const failure = snapshotToolExecutionError(error);
    let cleanup!: { sessionId: string; callId: string; settled: Promise<void> };
    const settled = (async () => {
      try {
        const claim = await claimPromise;
        if (claim.status === "owner") {
          await this.ledger.retryableFailure(claim.claim, failure);
        }
      } catch (cause) {
        if (!(cause instanceof ToolExecutionError)) {
          logRedactedFailure("late claim cleanup failed", cause);
        }
      } finally {
        this.claimCleanups.delete(cleanup);
      }
    })();
    cleanup = { sessionId, callId, settled };
    this.claimCleanups.add(cleanup);
  }

  private linkedSignal(
    context: ToolExecutionContext,
    toolTimeoutMs: number | undefined,
  ): LinkedSignal {
    const now = this.monotonicNow();
    const localDeadlineMonotonicMs = Math.min(
      toolTimeoutMs === undefined ? Number.POSITIVE_INFINITY : now + toolTimeoutMs,
      this.limits.timeoutMs === null ? Number.POSITIVE_INFINITY : now + this.limits.timeoutMs,
    );
    const turnDeadlineMonotonicMs = context.deadlineMonotonicMs ?? Number.POSITIVE_INFINITY;
    const turnDeadlineWins = turnDeadlineMonotonicMs <= localDeadlineMonotonicMs;
    const effectiveDeadlineMonotonicMs = Math.min(
      turnDeadlineMonotonicMs,
      localDeadlineMonotonicMs,
    );
    const controller = new AbortController();
    let kind: AbortKind | undefined;
    const abort = (next: AbortKind) => {
      if (controller.signal.aborted) return;
      kind = next;
      controller.abort(next);
    };
    const onParentAbort = () => abort("cancelled");
    context.signal.addEventListener("abort", onParentAbort, { once: true });
    if (context.signal.aborted) abort("cancelled");
    let timer: TimerHandle | undefined;
    if (Number.isFinite(effectiveDeadlineMonotonicMs) && !controller.signal.aborted) {
      timer = this.timerScheduler.schedule(
        Math.max(0, effectiveDeadlineMonotonicMs - this.monotonicNow()),
        () => {
          // Give cancellation delivered on the same scheduler tick priority.
          queueMicrotask(() => {
            if (context.signal.aborted) abort("cancelled");
            else abort(turnDeadlineWins ? "turn_timeout" : "tool_timeout");
          });
        },
      );
    }
    return {
      signal: controller.signal,
      deadlineMonotonicMs: Number.isFinite(effectiveDeadlineMonotonicMs)
        ? effectiveDeadlineMonotonicMs
        : undefined,
      kind: () => kind,
      cleanup: () => {
        timer?.cancel();
        context.signal.removeEventListener("abort", onParentAbort);
      },
    };
  }
}
