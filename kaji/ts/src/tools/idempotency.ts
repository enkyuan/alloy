import {
  IdempotencyCapacityError,
  IdempotencyConflictError,
  snapshotToolExecutionError,
  type ToolExecutionError,
} from "@/tools/execution-errors";
import { durableJsonSnapshot } from "@/events/json";
import { MAX_DURABLE_TOOL_RESULT_BYTES } from "@/events/schemas";

export type ToolLedgerOutcome =
  | { readonly status: "completed"; readonly result: unknown }
  | { readonly status: "failed"; readonly error: ToolExecutionError };

export interface ToolIdempotencyClaim {
  readonly sessionId: string;
  readonly toolCallId: string;
  readonly fingerprint: string;
}

export type ToolClaimResult =
  | { readonly status: "owner"; readonly claim: ToolIdempotencyClaim }
  | { readonly status: "running"; readonly outcome: Promise<ToolLedgerOutcome> }
  | { readonly status: "completed"; readonly result: unknown }
  | { readonly status: "unknown"; readonly error: ToolExecutionError };

/** Replaceable persistence boundary for exact tool-call idempotency. */
export interface ToolIdempotencyLedger {
  claim(sessionId: string, toolCallId: string, fingerprint: string): Promise<ToolClaimResult>;
  complete(claim: ToolIdempotencyClaim, result: unknown): Promise<void>;
  retryableFailure(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void>;
  unknownOutcome(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void>;
  releaseCompleted(sessionId: string): Promise<number>;
}

export interface InMemoryToolIdempotencyLedgerOptions {
  capacity?: number;
  completedTtlMs?: number;
  now?: () => number;
}

interface RunningEntry {
  readonly status: "running";
  readonly claim: ToolIdempotencyClaim;
  readonly outcome: Promise<ToolLedgerOutcome>;
  readonly resolve: (outcome: ToolLedgerOutcome) => void;
}

interface CompletedEntry {
  readonly status: "completed";
  readonly claim: ToolIdempotencyClaim;
  readonly result: unknown;
  readonly completedAt: number;
  lastAccessed: number;
}

interface UnknownEntry {
  readonly status: "unknown";
  readonly claim: ToolIdempotencyClaim;
  readonly error: ToolExecutionError;
}

type LedgerEntry = RunningEntry | CompletedEntry | UnknownEntry;

function keyFor(sessionId: string, toolCallId: string): string {
  return JSON.stringify([sessionId, toolCallId]);
}

function detachResult(result: unknown): unknown {
  return durableJsonSnapshot(result, "tool_result", MAX_DURABLE_TOOL_RESULT_BYTES);
}

function assertPositiveInteger(value: number, name: string): void {
  if (!Number.isInteger(value) || value < 1) throw new RangeError(`${name} must be positive`);
}

/** Process-local bounded ledger. Running and unknown entries are never evicted. */
export class InMemoryToolIdempotencyLedger implements ToolIdempotencyLedger {
  private readonly entries = new Map<string, LedgerEntry>();
  private readonly capacity: number;
  private readonly completedTtlMs: number;
  private readonly now: () => number;

  constructor(options: InMemoryToolIdempotencyLedgerOptions = {}) {
    this.capacity = options.capacity ?? 10_000;
    this.completedTtlMs = options.completedTtlMs ?? 24 * 60 * 60 * 1_000;
    assertPositiveInteger(this.capacity, "capacity");
    assertPositiveInteger(this.completedTtlMs, "completedTtlMs");
    this.now = options.now ?? (() => globalThis.performance.now());
  }

  async claim(
    sessionId: string,
    toolCallId: string,
    fingerprint: string,
  ): Promise<ToolClaimResult> {
    const key = keyFor(sessionId, toolCallId);
    let existing = this.entries.get(key);
    if (
      existing?.status === "completed" &&
      this.now() - existing.completedAt >= this.completedTtlMs
    ) {
      this.entries.delete(key);
      existing = undefined;
    }
    if (existing !== undefined) {
      if (existing.claim.fingerprint !== fingerprint) throw new IdempotencyConflictError();
      if (existing.status === "running") return { status: "running", outcome: existing.outcome };
      if (existing.status === "unknown") return { status: "unknown", error: existing.error };
      existing.lastAccessed = this.now();
      this.entries.delete(key);
      this.entries.set(key, existing);
      return { status: "completed", result: detachResult(existing.result) };
    }

    this.evictCompletedForCapacity();
    if (this.entries.size >= this.capacity) throw new IdempotencyCapacityError();

    let resolve!: (outcome: ToolLedgerOutcome) => void;
    const outcome = new Promise<ToolLedgerOutcome>((done) => {
      resolve = done;
    });
    const claim = Object.freeze({ sessionId, toolCallId, fingerprint });
    this.entries.set(key, { status: "running", claim, outcome, resolve });
    return { status: "owner", claim };
  }

  async complete(claim: ToolIdempotencyClaim, result: unknown): Promise<void> {
    const { key, entry } = this.runningEntry(claim);
    const detached = detachResult(result);
    const completedAt = this.now();
    this.entries.set(key, {
      status: "completed",
      claim: entry.claim,
      result: detached,
      completedAt,
      lastAccessed: completedAt,
    });
    entry.resolve({ status: "completed", result: detachResult(detached) });
  }

  async retryableFailure(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    const { key, entry } = this.runningEntry(claim);
    entry.resolve({ status: "failed", error: snapshotToolExecutionError(error) });
    this.entries.delete(key);
  }

  async unknownOutcome(claim: ToolIdempotencyClaim, error: ToolExecutionError): Promise<void> {
    const { key, entry } = this.runningEntry(claim);
    const snapshot = snapshotToolExecutionError(error);
    this.entries.set(key, { status: "unknown", claim: entry.claim, error: snapshot });
    entry.resolve({ status: "failed", error: snapshot });
  }

  async releaseCompleted(sessionId: string): Promise<number> {
    let released = 0;
    for (const [key, entry] of this.entries) {
      if (entry.status === "completed" && entry.claim.sessionId === sessionId) {
        this.entries.delete(key);
        released++;
      }
    }
    return released;
  }

  private runningEntry(claim: ToolIdempotencyClaim): { key: string; entry: RunningEntry } {
    const key = keyFor(claim.sessionId, claim.toolCallId);
    const entry = this.entries.get(key);
    if (entry?.status !== "running" || entry.claim !== claim) {
      throw new Error("Tool idempotency claim is no longer running");
    }
    return { key, entry };
  }

  private evictCompletedForCapacity(): void {
    const now = this.now();
    for (const [key, entry] of this.entries) {
      if (entry.status === "completed" && now - entry.completedAt >= this.completedTtlMs) {
        this.entries.delete(key);
      }
    }
    while (this.entries.size >= this.capacity) {
      let lruKey: string | undefined;
      let lruAccess = Number.POSITIVE_INFINITY;
      for (const [key, entry] of this.entries) {
        if (entry.status === "completed" && entry.lastAccessed < lruAccess) {
          lruKey = key;
          lruAccess = entry.lastAccessed;
        }
      }
      if (lruKey === undefined) return;
      this.entries.delete(lruKey);
    }
  }
}
