import { createHash } from "node:crypto";

import { throwIfCancellationRequested, type CancellationTokenLike } from "@/runtime/cancellation";
import { ProviderCancellationContractViolation, TurnTimeoutError } from "@/runtime/limits";
import type {
  ObservableCancellationToken,
  SessionTurnCoordinator,
  SessionTurnLease,
  TurnLeaseOptions,
} from "@/runtime/session/coordinator";
import { systemClock } from "@/internal/uuid";

type Sql = any;

/** Return the signed bigint advisory-lock key shared with the Python SDK. */
export function postgresLockKey(sessionId: string): bigint {
  if (sessionId.trim().length === 0) throw new TypeError("sessionId must be a non-empty string");
  return createHash("sha256").update(sessionId, "utf8").digest().readBigInt64BE(0);
}

/** Cross-process session coordination using a reserved Postgres pool connection. */
export class PostgresTurnCoordinator implements SessionTurnCoordinator {
  private sql: Sql | undefined;
  private readonly held = new Set<string>();
  private readonly quarantined = new Set<string>();

  constructor(
    private readonly url: string,
    private readonly maxConnections = 10,
    private readonly pollIntervalMs = 50,
  ) {
    if (url.trim().length === 0) throw new TypeError("url must be a non-empty string");
    if (!Number.isInteger(maxConnections) || maxConnections < 1) {
      throw new RangeError("maxConnections must be at least one");
    }
    if (!Number.isInteger(pollIntervalMs) || pollIntervalMs < 1) {
      throw new RangeError("pollIntervalMs must be a positive integer");
    }
  }

  async runExclusive<T>(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
    operation: () => Promise<T>,
  ): Promise<T> {
    const lease = await this.acquire(sessionId, token);
    try {
      throwIfCancellationRequested(token);
      return await operation();
    } finally {
      await lease.release();
    }
  }

  async acquire(
    sessionId: string,
    token?: ObservableCancellationToken,
    options: TurnLeaseOptions = {},
  ): Promise<SessionTurnLease> {
    const key = postgresLockKey(sessionId);
    throwIfCancellationRequested(token);
    if (token !== undefined && token.signal === undefined) {
      throw new TypeError("Session turn cancellation requires an AbortSignal");
    }
    const deadline = options.deadlineMonotonicMs;
    if (deadline !== undefined && (!Number.isFinite(deadline) || typeof deadline !== "number")) {
      throw new RangeError("deadlineMonotonicMs must be finite");
    }
    const clock = options.clock ?? systemClock;
    if (deadline !== undefined && clock.nowMonotonic() >= deadline) {
      throw new TurnTimeoutError("queue", true, "not_started");
    }
    if (this.quarantined.has(sessionId)) throw new ProviderCancellationContractViolation();

    while (true) {
      throwIfCancellationRequested(token);
      if (deadline !== undefined && clock.nowMonotonic() >= deadline) {
        throw new TurnTimeoutError("queue", true, "not_started");
      }
      const reserved = await (await this.client()).reserve();
      try {
        const rows = (await reserved`
          SELECT pg_try_advisory_lock(${key}) AS acquired
        `) as Array<{ acquired: boolean }>;
        if (rows[0]?.acquired) {
          this.held.add(sessionId);
          return this.lease(sessionId, key, reserved);
        }
      } catch (error) {
        await reserved.release();
        throw error;
      }
      await reserved.release();
      const remaining =
        deadline === undefined ? this.pollIntervalMs : deadline - clock.nowMonotonic();
      await waitForLock(Math.max(0, Math.min(this.pollIntervalMs, remaining)), token);
    }
  }

  quarantine(sessionId: string): void {
    if (!this.held.has(sessionId)) {
      throw new Error("Cannot quarantine a session without a held lease");
    }
    this.quarantined.add(sessionId);
  }

  clearQuarantine(sessionId: string): void {
    this.quarantined.delete(sessionId);
  }

  async close(): Promise<void> {
    await this.sql?.end({ timeout: 5 });
    this.sql = undefined;
  }

  private async client(): Promise<Sql> {
    if (this.sql === undefined) {
      const { default: postgres } = await import("postgres");
      this.sql = postgres(this.url, { max: this.maxConnections });
    }
    return this.sql;
  }

  private lease(sessionId: string, key: bigint, reserved: Sql): SessionTurnLease {
    let released = false;
    const lease: SessionTurnLease = {
      transfer: () => {
        if (released) throw new Error("Cannot transfer a released turn lease");
        return lease;
      },
      release: async () => {
        if (released) return;
        released = true;
        try {
          await reserved`SELECT pg_advisory_unlock(${key})`;
        } finally {
          this.held.delete(sessionId);
          await reserved.release();
        }
      },
    };
    return lease;
  }
}

async function waitForLock(
  delayMs: number,
  token: CancellationTokenLike | undefined,
): Promise<void> {
  if (token?.signal === undefined) {
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
    return;
  }
  const signal = token.signal;
  await new Promise<void>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout>;
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new Error("cancelled"));
    };
    timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    signal.addEventListener("abort", abort, { once: true });
  }).catch(() => throwIfCancellationRequested(token));
  throwIfCancellationRequested(token);
}
