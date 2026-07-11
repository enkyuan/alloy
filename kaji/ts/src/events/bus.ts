import { EventBufferOverflowError } from "@/events/errors";
import type { EventBusProtocol, EventBusSubscribeOptions } from "@/events/protocols";
import type { KajiEvent } from "@/events/schemas";

function eventSequence(event: { readonly session_id: string }): number | undefined {
  const sequence = (event as { readonly sequence?: unknown }).sequence;
  return typeof sequence === "number" ? sequence : undefined;
}

/** Bounded async queue using a ring buffer; no history is retained by the bus. */
export class RingBufferSubscription<
  TEvent extends { readonly session_id: string },
> implements AsyncIterableIterator<TEvent> {
  private readonly buffer: Array<TEvent | undefined>;
  private head = 0;
  private size = 0;
  private pending:
    | {
        resolve: (result: IteratorResult<TEvent>) => void;
        reject: (error: unknown) => void;
      }
    | undefined;
  private closed = false;
  private terminalError: Error | undefined;
  private errorDelivered = false;
  private lastSequence: number;

  constructor(
    capacity: number,
    private readonly onReturn: () => void,
    afterSequence = 0,
  ) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new RangeError("subscriber capacity must be a positive integer");
    }
    if (!Number.isInteger(afterSequence) || afterSequence < 0) {
      throw new RangeError("afterSequence must be a non-negative integer");
    }
    this.buffer = new Array(capacity);
    this.lastSequence = afterSequence;
  }

  get isClosed(): boolean {
    return this.closed;
  }

  advanceCursor(sequence: number): void {
    if (sequence > this.lastSequence) this.lastSequence = sequence;
  }

  push(event: TEvent): void {
    if (this.closed) return;
    const sequence = eventSequence(event);
    if (sequence !== undefined && sequence <= this.lastSequence) return;
    if (this.pending !== undefined) {
      const pending = this.pending;
      this.pending = undefined;
      if (sequence !== undefined) this.lastSequence = sequence;
      pending.resolve({ value: event, done: false });
      return;
    }
    if (this.size === this.buffer.length) {
      this.fail(new EventBufferOverflowError(this.lastSequence, sequence ?? this.lastSequence));
      return;
    }
    this.buffer[(this.head + this.size) % this.buffer.length] = event;
    this.size += 1;
  }

  next(): Promise<IteratorResult<TEvent>> {
    if (this.size > 0) {
      const event = this.buffer[this.head]!;
      this.buffer[this.head] = undefined;
      this.head = (this.head + 1) % this.buffer.length;
      this.size -= 1;
      const sequence = eventSequence(event);
      if (sequence !== undefined) this.lastSequence = sequence;
      return Promise.resolve({ value: event, done: false });
    }
    if (this.terminalError !== undefined && !this.errorDelivered) {
      this.errorDelivered = true;
      return Promise.reject(this.terminalError);
    }
    if (this.closed) return Promise.resolve({ value: undefined, done: true });
    if (this.pending !== undefined) {
      return Promise.reject(new Error("Concurrent next() calls are not supported"));
    }
    return new Promise((resolve, reject) => {
      this.pending = { resolve, reject };
    });
  }

  return(): Promise<IteratorResult<TEvent>> {
    this.close();
    return Promise.resolve({ value: undefined, done: true });
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.size = 0;
    this.head = 0;
    if (this.pending !== undefined) {
      this.pending.resolve({ value: undefined, done: true });
      this.pending = undefined;
    }
    this.onReturn();
  }

  private fail(error: Error): void {
    if (this.closed) return;
    this.terminalError = error;
    this.closed = true;
    this.size = 0;
    this.head = 0;
    if (this.pending !== undefined) {
      this.pending.reject(error);
      this.pending = undefined;
      this.errorDelivered = true;
    }
    this.onReturn();
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<TEvent> {
    return this;
  }
}

export class EventBus<
  TEvent extends { readonly session_id: string } = KajiEvent,
> implements EventBusProtocol<TEvent> {
  private readonly subscribers = new Map<string, Set<RingBufferSubscription<TEvent>>>();

  constructor(private readonly subscriberCapacity = 1_024) {
    if (!Number.isInteger(subscriberCapacity) || subscriberCapacity <= 0) {
      throw new RangeError("subscriberCapacity must be a positive integer");
    }
  }

  async publish(event: TEvent): Promise<void> {
    for (const subscriber of this.subscribers.get(event.session_id) ?? []) {
      subscriber.push(event);
    }
  }

  subscribe(
    sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<TEvent> {
    const afterSequence = options.afterSequence ?? 0;
    let subscribers = this.subscribers.get(sessionId);
    if (subscribers === undefined) {
      subscribers = new Set();
      this.subscribers.set(sessionId, subscribers);
    }
    const bucket = subscribers;
    const subscription = new RingBufferSubscription<TEvent>(
      this.subscriberCapacity,
      () => {
        bucket.delete(subscription);
        if (bucket.size === 0) this.subscribers.delete(sessionId);
      },
      afterSequence,
    );
    bucket.add(subscription);
    return subscription;
  }

  close(): void {
    for (const subscribers of this.subscribers.values()) {
      for (const subscriber of [...subscribers]) subscriber.close();
    }
    this.subscribers.clear();
  }
}
