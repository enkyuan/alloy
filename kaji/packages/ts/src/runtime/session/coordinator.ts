import {
  CancellationError,
  throwIfCancellationRequested,
  type CancellationTokenLike,
} from "@/runtime/cancellation";
import {
  systemClock,
  systemTimerScheduler,
  type Clock,
  type TimerHandle,
  type TimerScheduler,
} from "@/internal/uuid";
import { ProviderCancellationContractViolation, TurnTimeoutError } from "@/runtime/limits";

/** Cancellation token whose state changes can be observed while queued. */
export interface ObservableCancellationToken extends CancellationTokenLike {
  readonly signal: AbortSignal;
}

/** Process-local serialization boundary for turns that share a session. */
export interface SessionTurnCoordinator {
  acquire(
    sessionId: string,
    token?: ObservableCancellationToken,
    options?: TurnLeaseOptions,
  ): Promise<SessionTurnLease>;
  quarantine(sessionId: string): void | Promise<void>;
  clearQuarantine(sessionId: string): void | Promise<void>;
  runExclusive<T>(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
    operation: () => Promise<T>,
  ): Promise<T>;
}

export interface TurnLeaseOptions {
  readonly deadlineMonotonicMs?: number;
  readonly clock?: Clock;
  readonly scheduler?: TimerScheduler;
}

/** Exclusive ownership that may be transferred to runtime quarantine. */
export interface SessionTurnLease {
  transfer(): SessionTurnLease;
  release(): void | Promise<void>;
}

interface Waiter {
  settled: boolean;
  linked: boolean;
  previous?: Waiter;
  next?: Waiter;
  resolve: () => void;
  reject: (error: unknown) => void;
  removeAbortListener?: () => void;
  timer?: TimerHandle;
}

interface SessionEntry {
  head?: Waiter;
  tail?: Waiter;
  waiterCount: number;
  held: boolean;
  quarantined: boolean;
}

function cancellationError(token: ObservableCancellationToken): unknown {
  try {
    throwIfCancellationRequested(token);
  } catch (error) {
    return error;
  }
  return new CancellationError();
}

/**
 * FIFO keyed coordinator for one process. Different session IDs never share a
 * queue; callers that need cross-process serialization must inject another
 * implementation.
 */
export class InMemorySessionTurnCoordinator implements SessionTurnCoordinator {
  private readonly entries = new Map<string, SessionEntry>();

  /** Number of session queues currently held or waiting. */
  get entryCount(): number {
    return this.entries.size;
  }

  /** Total actively linked waiters across session queues. */
  get waitingCount(): number {
    let count = 0;
    for (const entry of this.entries.values()) count += entry.waiterCount;
    return count;
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
    throwIfCancellationRequested(token);
    if (token !== undefined && token.signal === undefined) {
      throw new TypeError("Session turn cancellation requires an AbortSignal");
    }
    if (token?.signal?.aborted) throw cancellationError(token);
    const clock = options.clock ?? systemClock;
    const scheduler = options.scheduler ?? systemTimerScheduler;
    const deadline = options.deadlineMonotonicMs;
    if (deadline !== undefined && (typeof deadline !== "number" || !Number.isFinite(deadline))) {
      throw new RangeError("deadlineMonotonicMs must be finite");
    }
    if (deadline !== undefined && clock.nowMonotonic() >= deadline) {
      throw new TurnTimeoutError("queue", true, "not_started");
    }
    const existing = this.entries.get(sessionId);
    if (existing === undefined) {
      const entry: SessionEntry = { waiterCount: 0, held: true, quarantined: false };
      this.entries.set(sessionId, entry);
      return this.lease(sessionId, entry);
    }
    if (existing.quarantined) throw new ProviderCancellationContractViolation();

    const entry = await new Promise<SessionEntry>((resolve, reject) => {
      const waiter: Waiter = {
        settled: false,
        linked: true,
        resolve: () => resolve(existing),
        reject,
      };
      this.enqueue(existing, waiter);

      const signal = token?.signal;
      let wakeQueued = false;
      const wake = (): void => {
        if (wakeQueued) return;
        wakeQueued = true;
        queueMicrotask(() => {
          wakeQueued = false;
          if (waiter.settled) return;
          if (token?.signal.aborted) {
            waiter.settled = true;
            this.unlink(existing, waiter);
            waiter.removeAbortListener?.();
            waiter.timer?.cancel();
            reject(cancellationError(token));
            return;
          }
          if (deadline !== undefined && clock.nowMonotonic() >= deadline) {
            waiter.settled = true;
            this.unlink(existing, waiter);
            waiter.removeAbortListener?.();
            waiter.timer?.cancel();
            reject(new TurnTimeoutError("queue", true, "not_started"));
          }
        });
      };
      const onAbort = (): void => {
        if (waiter.settled) return;
        wake();
      };
      if (signal !== undefined) {
        waiter.removeAbortListener = () => signal.removeEventListener("abort", onAbort);
        signal.addEventListener("abort", onAbort, { once: true });
        if (signal.aborted) onAbort();
      }
      if (deadline !== undefined) {
        waiter.timer = scheduler.schedule(Math.max(0, deadline - clock.nowMonotonic()), wake);
      }
    });
    if (token?.signal.aborted) {
      this.release(sessionId, entry);
      throw cancellationError(token);
    }
    if (deadline !== undefined && clock.nowMonotonic() >= deadline) {
      this.release(sessionId, entry);
      throw new TurnTimeoutError("queue", true, "not_started");
    }
    return this.lease(sessionId, entry);
  }

  quarantine(sessionId: string): void {
    const entry = this.entries.get(sessionId);
    if (entry === undefined || !entry.held) {
      throw new Error("Cannot quarantine a session without a held lease");
    }
    entry.quarantined = true;
    while (entry.head !== undefined) {
      const waiter = entry.head;
      this.unlink(entry, waiter);
      if (waiter.settled) continue;
      waiter.settled = true;
      waiter.removeAbortListener?.();
      waiter.timer?.cancel();
      waiter.reject(new ProviderCancellationContractViolation());
    }
  }

  clearQuarantine(sessionId: string): void {
    const entry = this.entries.get(sessionId);
    if (entry === undefined) return;
    entry.quarantined = false;
    if (!entry.held && entry.waiterCount === 0 && this.entries.get(sessionId) === entry) {
      this.entries.delete(sessionId);
    }
  }

  private lease(sessionId: string, entry: SessionEntry): SessionTurnLease {
    let released = false;
    const lease: SessionTurnLease = {
      transfer: () => lease,
      release: () => {
        if (released) return;
        released = true;
        this.release(sessionId, entry);
      },
    };
    return lease;
  }

  private enqueue(entry: SessionEntry, waiter: Waiter): void {
    waiter.previous = entry.tail;
    if (entry.tail === undefined) entry.head = waiter;
    else entry.tail.next = waiter;
    entry.tail = waiter;
    entry.waiterCount += 1;
  }

  private unlink(entry: SessionEntry, waiter: Waiter): void {
    if (!waiter.linked) return;
    if (waiter.previous === undefined) entry.head = waiter.next;
    else waiter.previous.next = waiter.next;
    if (waiter.next === undefined) entry.tail = waiter.previous;
    else waiter.next.previous = waiter.previous;
    waiter.previous = undefined;
    waiter.next = undefined;
    waiter.linked = false;
    entry.waiterCount -= 1;
  }

  private release(sessionId: string, entry: SessionEntry): void {
    if (entry.quarantined) {
      entry.held = false;
      return;
    }
    while (entry.head !== undefined) {
      const waiter = entry.head;
      this.unlink(entry, waiter);
      if (waiter.settled) continue;
      waiter.settled = true;
      waiter.removeAbortListener?.();
      waiter.timer?.cancel();
      waiter.resolve();
      return;
    }
    entry.held = false;
    if (this.entries.get(sessionId) === entry) {
      this.entries.delete(sessionId);
    }
  }
}
