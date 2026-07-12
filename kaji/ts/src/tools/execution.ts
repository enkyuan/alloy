import { snapshotToolExecutionContext, type ToolExecutionContext } from "@/runtime/context";
import { DurableJsonLimitError, InvalidDurableValueError } from "@/events/errors";
import { durableJsonSnapshot } from "@/events/json";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/schemas";
import { logRedactedFailure } from "@/internal/safe-logging";
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
  | { readonly status: "failed"; readonly error: ToolExecutionError };

export interface ToolExecutionRequest {
  readonly name: string;
  readonly args: Readonly<Record<string, unknown>>;
  readonly context: ToolExecutionContext;
  readonly timeoutMs?: number;
  readonly exclusive: boolean;
  readonly onStarted: () => Promise<void>;
  readonly execute: (context: ToolExecutionContext) => Promise<unknown>;
}

export interface ToolExecutionControllerOptions {
  limits?: Partial<ToolExecutionLimits>;
  ledger?: ToolIdempotencyLedger;
  now?: () => number;
  monotonicNow?: () => number;
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

type AbortKind = "cancelled" | "timeout";

interface LinkedSignal {
  readonly signal: AbortSignal;
  readonly deadlineMs: number | undefined;
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
    outcome.error.error_code === "TOOL_TIMEOUT"
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
  private readonly now: () => number;
  private readonly monotonicNow: () => number;
  private readonly metrics: MetricsSink;
  private readonly trace: TraceSink;
  private readonly active = new Map<string, { callId: string; settled: Promise<void> }>();
  private readonly claimCleanups = new Set<Promise<void>>();

  constructor(options: ToolExecutionControllerOptions = {}) {
    this.limits = Object.freeze({ ...DEFAULT_TOOL_EXECUTION_LIMITS, ...options.limits });
    validateLimits(this.limits);
    this.ledger = options.ledger ?? new InMemoryToolIdempotencyLedger();
    this.permits = new PermitPool(this.limits.maxParallel);
    this.now = options.now ?? Date.now;
    this.monotonicNow = options.monotonicNow ?? (() => globalThis.performance.now());
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.trace = options.traceSink ?? NOOP_TRACE;
  }

  async execute(request: ToolExecutionRequest): Promise<ToolExecutionControllerOutcome> {
    const canonicalContext = snapshotExecutionRequestContext(request.context);
    const started = this.monotonicNow();
    const span = startSpan(this.trace, "kaji.tool", {
      "principal.id": canonicalContext.principalId,
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
      const error = this.abortError(linked.kind(), "not_started");
      this.scheduleLateClaimCleanup(claimPromise, error);
      linked.cleanup();
      return { status: "failed", error };
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
      const error = this.abortError(linked.kind(), "not_started");
      if (claimResult.status === "owner") {
        await this.ledger.retryableFailure(claimResult.claim, error);
      }
      linked.cleanup();
      return { status: "failed", error };
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
      const error = this.abortError(linked.kind(), "not_started");
      recordMetric(
        this.metrics,
        "kaji.tool.queue_wait_ms",
        Math.max(0, this.monotonicNow() - queueStarted),
        { outcome: error.error_code === "TOOL_TIMEOUT" ? "timeout" : "cancelled" },
      );
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      return { status: "failed", error };
    }

    recordMetric(
      this.metrics,
      "kaji.tool.queue_wait_ms",
      Math.max(0, this.monotonicNow() - queueStarted),
      { outcome: "acquired" },
    );

    if (linked.signal.aborted) {
      release();
      const error = this.abortError(linked.kind(), "not_started");
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      return { status: "failed", error };
    }

    try {
      await request.onStarted();
    } catch (cause) {
      release();
      const error = toolStartRecordFailed(cause);
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      throw new ToolStartRecordingError(error, cause);
    }

    if (linked.signal.aborted) {
      release();
      const error = this.abortError(linked.kind(), "not_started");
      await this.ledger.retryableFailure(claim, error);
      linked.cleanup();
      return { status: "failed", error };
    }

    const executionContext = snapshotToolExecutionContext({
      ...canonicalContext,
      signal: linked.signal,
      ...(linked.deadlineMs === undefined ? {} : { deadlineMs: linked.deadlineMs }),
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
    this.active.set(key, { callId: canonicalContext.toolCallId, settled: tracked });
    recordMetric(this.metrics, "kaji.tool.active", this.active.size, {});

    const abort = new Promise<ToolExecutionControllerOutcome>((resolve) => {
      const finish = () => {
        const error = this.abortError(linked.kind(), "unknown");
        resolve({ status: "failed", error });
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
    if (outcome.error.outcome === "failed" && outcome.error.retryable) {
      await this.ledger.retryableFailure(claim, outcome.error);
    } else {
      await this.ledger.unknownOutcome(claim, outcome.error);
    }
    return outcome;
  }

  /** Wait for real handler settlement; report calls still running at the deadline. */
  async drain(timeoutMs: number): Promise<readonly string[]> {
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
      throw new RangeError("timeoutMs must be a finite non-negative number");
    }
    const active = [...this.active.values()].map(({ settled }) => settled);
    if (active.length > 0) {
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        await Promise.race([
          Promise.allSettled(active),
          new Promise<void>((resolve) => {
            timer = setTimeout(resolve, timeoutMs);
          }),
        ]);
      } finally {
        if (timer !== undefined) clearTimeout(timer);
      }
    }
    return [...this.active.values()].map(({ callId }) => callId).sort();
  }

  private abortError(
    kind: AbortKind | undefined,
    outcome: "not_started" | "unknown",
  ): ToolExecutionError {
    return kind === "timeout" ? toolTimedOut(outcome) : toolCancelled(outcome);
  }

  private async waitForRunningOutcome(
    running: Promise<ToolLedgerOutcome>,
    linked: LinkedSignal,
  ): Promise<ToolExecutionControllerOutcome> {
    let removeAbortListener = () => {};
    try {
      const aborted = new Promise<ToolExecutionControllerOutcome>((resolve) => {
        const finish = () => {
          resolve({ status: "failed", error: this.abortError(linked.kind(), "unknown") });
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
    claimPromise: Promise<ToolClaimResult>,
    error: ToolExecutionError,
  ): void {
    const failure = snapshotToolExecutionError(error);
    let cleanup!: Promise<void>;
    cleanup = (async () => {
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
    this.claimCleanups.add(cleanup);
  }

  private linkedSignal(
    context: ToolExecutionContext,
    toolTimeoutMs: number | undefined,
  ): LinkedSignal {
    const now = this.now();
    const deadlines = [context.deadlineMs];
    if (toolTimeoutMs !== undefined) deadlines.push(now + toolTimeoutMs);
    if (this.limits.timeoutMs !== null) deadlines.push(now + this.limits.timeoutMs);
    const finite = deadlines.filter((value): value is number => value !== undefined);
    const deadlineMs = finite.length === 0 ? undefined : Math.min(...finite);
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
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (deadlineMs !== undefined && !controller.signal.aborted) {
      const schedule = () => {
        const remaining = deadlineMs - this.now();
        if (remaining <= 0) abort("timeout");
        else timer = setTimeout(schedule, Math.min(remaining, 2_147_483_647));
      };
      schedule();
    }
    return {
      signal: controller.signal,
      deadlineMs,
      kind: () => kind,
      cleanup: () => {
        if (timer !== undefined) clearTimeout(timer);
        context.signal.removeEventListener("abort", onParentAbort);
      },
    };
  }
}
