import {
  CancellationError,
  throwIfCancellationRequested,
  type CancellationTokenLike,
} from "@/runtime/cancellation";

/** Cancellation token whose state changes can be observed while queued. */
export interface ObservableCancellationToken extends CancellationTokenLike {
  readonly signal: AbortSignal;
}

/** Process-local serialization boundary for turns that share a session. */
export interface SessionTurnCoordinator {
  runExclusive<T>(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
    operation: () => Promise<T>,
  ): Promise<T>;
}

interface Waiter {
  settled: boolean;
  linked: boolean;
  previous?: Waiter;
  next?: Waiter;
  resolve: () => void;
  reject: (error: unknown) => void;
  removeAbortListener?: () => void;
}

interface SessionEntry {
  head?: Waiter;
  tail?: Waiter;
  waiterCount: number;
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
    throwIfCancellationRequested(token);
    if (token !== undefined && token.signal === undefined) {
      throw new TypeError("Session turn cancellation requires an AbortSignal");
    }
    if (token?.signal?.aborted) throw cancellationError(token);
    const entry = await this.acquire(sessionId, token);
    try {
      throwIfCancellationRequested(token);
      return await operation();
    } finally {
      this.release(sessionId, entry);
    }
  }

  private acquire(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
  ): Promise<SessionEntry> {
    const existing = this.entries.get(sessionId);
    if (existing === undefined) {
      const entry: SessionEntry = { waiterCount: 0 };
      this.entries.set(sessionId, entry);
      return Promise.resolve(entry);
    }

    return new Promise<SessionEntry>((resolve, reject) => {
      const waiter: Waiter = {
        settled: false,
        linked: true,
        resolve: () => resolve(existing),
        reject,
      };
      this.enqueue(existing, waiter);

      const signal = token?.signal;
      if (signal === undefined) return;
      const onAbort = (): void => {
        if (waiter.settled) return;
        waiter.settled = true;
        this.unlink(existing, waiter);
        waiter.removeAbortListener?.();
        reject(token === undefined ? new CancellationError() : cancellationError(token));
      };
      waiter.removeAbortListener = () => signal.removeEventListener("abort", onAbort);
      signal.addEventListener("abort", onAbort, { once: true });
      if (signal.aborted) onAbort();
    });
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
    while (entry.head !== undefined) {
      const waiter = entry.head;
      this.unlink(entry, waiter);
      if (waiter.settled) continue;
      waiter.settled = true;
      waiter.removeAbortListener?.();
      waiter.resolve();
      return;
    }
    if (this.entries.get(sessionId) === entry) {
      this.entries.delete(sessionId);
    }
  }
}
