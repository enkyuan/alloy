import { RingBufferSubscription } from "@/events/bus";
import {
  EventBufferOverflowError,
  EventDeliveryError,
  EventIdConflictError,
  EventStoreCapacityError,
} from "@/events/errors";
import { structurallyEqualJson } from "@/events/json";
import type { EventBusProtocol, EventCommitter } from "@/events/protocols";
import {
  type KajiEvent,
  NewKajiEvent,
  type NewKajiEvent as NewKajiEventType,
  StoredKajiEvent,
} from "@/events/schemas";
import { InMemoryEventStore, type EventStore } from "@/events/store";

class SerialExecutor {
  private tail = Promise.resolve();

  run<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.tail.then(operation, operation);
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }
}

class AttachedSubscription implements AsyncIterableIterator<StoredKajiEvent> {
  private cursor: number;
  private backlog: readonly StoredKajiEvent[] | undefined;
  private backlogIndex = 0;
  private closed = false;

  constructor(
    private readonly inner: RingBufferSubscription<StoredKajiEvent>,
    private readonly ready: Promise<
      | { readonly attached: true; readonly backlog: readonly StoredKajiEvent[] }
      | { readonly attached: false; readonly error: unknown }
    >,
    afterSequence: number,
  ) {
    this.cursor = afterSequence;
  }

  async next(): Promise<IteratorResult<StoredKajiEvent>> {
    if (this.closed) return { value: undefined, done: true };
    try {
      if (this.backlog === undefined) {
        const ready = await this.ready;
        if (!ready.attached) throw ready.error;
        this.backlog = ready.backlog;
      }
      const event = this.backlog[this.backlogIndex];
      if (event !== undefined) {
        this.backlogIndex += 1;
        this.cursor = event.sequence;
        this.inner.advanceCursor(this.cursor);
        return { value: event, done: false };
      }
      const next = await this.inner.next();
      if (next.done) this.closed = true;
      return next;
    } catch (error) {
      await this.close();
      if (error instanceof EventBufferOverflowError && error.lastSequence < this.cursor) {
        throw new EventBufferOverflowError(this.cursor, error.latestSequence);
      }
      throw error;
    }
  }

  async return(): Promise<IteratorResult<StoredKajiEvent>> {
    await this.close();
    return { value: undefined, done: true };
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<StoredKajiEvent> {
    return this;
  }

  private async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    await this.inner.return();
  }
}

class SplitSubscription implements AsyncIterableIterator<StoredKajiEvent> {
  private cursor: number;
  private backlog: readonly StoredKajiEvent[] | undefined;
  private backlogIndex = 0;
  private closed = false;

  constructor(
    private readonly live: AsyncIterableIterator<KajiEvent | StoredKajiEvent>,
    private readonly store: EventStore,
    private readonly sessionId: string,
    private readonly subscriberCapacity: number,
    afterSequence: number,
  ) {
    this.cursor = afterSequence;
  }

  async next(): Promise<IteratorResult<StoredKajiEvent>> {
    if (this.closed) return { value: undefined, done: true };
    try {
      if (this.backlog === undefined) {
        const backlog = await this.store.getEvents(this.sessionId, {
          afterSequence: this.cursor,
          limit: this.subscriberCapacity + 1,
        });
        if (backlog.length > this.subscriberCapacity) {
          throw new EventBufferOverflowError(
            this.cursor,
            await this.store.lastSequence(this.sessionId),
          );
        }
        this.backlog = backlog;
      }
      const backlogEvent = this.backlog[this.backlogIndex];
      if (backlogEvent !== undefined) {
        this.backlogIndex += 1;
        this.cursor = backlogEvent.sequence;
        return { value: backlogEvent, done: false };
      }
      while (true) {
        const candidate = await this.live.next();
        if (candidate.done) {
          await this.close();
          return { value: undefined, done: true };
        }
        const event = StoredKajiEvent.parse(candidate.value);
        if (event.sequence <= this.cursor) continue;
        this.cursor = event.sequence;
        return { value: event, done: false };
      }
    } catch (error) {
      await this.close();
      if (error instanceof EventBufferOverflowError && error.lastSequence < this.cursor) {
        throw new EventBufferOverflowError(this.cursor, error.latestSequence);
      }
      throw error;
    }
  }

  async return(): Promise<IteratorResult<StoredKajiEvent>> {
    await this.close();
    return { value: undefined, done: true };
  }

  [Symbol.asyncIterator](): AsyncIterableIterator<StoredKajiEvent> {
    return this;
  }

  private async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    await this.live.return?.();
  }
}

export interface InMemoryEventCommitterOptions {
  subscriberCapacity?: number;
}

export interface SplitEventCommitterOptions {
  subscriberCapacity?: number;
  maxPendingEvents?: number;
}

/** Stable single-process append + fanout boundary. */
export class InMemoryEventCommitter implements EventCommitter {
  private readonly serial = new SerialExecutor();
  private readonly subscribers = new Map<string, Set<RingBufferSubscription<StoredKajiEvent>>>();
  private readonly subscriberCapacity: number;

  constructor(
    readonly store: EventStore = new InMemoryEventStore(),
    options: InMemoryEventCommitterOptions = {},
  ) {
    this.subscriberCapacity = options.subscriberCapacity ?? 1_024;
    if (!Number.isInteger(this.subscriberCapacity) || this.subscriberCapacity <= 0) {
      throw new RangeError("subscriberCapacity must be a positive integer");
    }
  }

  commit(event: NewKajiEventType): Promise<StoredKajiEvent> {
    return this.serial.run(async () => {
      let result;
      try {
        result = await this.store.append(event);
      } catch (cause) {
        if (cause instanceof EventIdConflictError || cause instanceof EventStoreCapacityError) {
          throw cause;
        }
        throw new EventDeliveryError("append", event.id, false, { cause });
      }
      if (result.inserted) {
        for (const subscriber of this.subscribers.get(result.event.session_id) ?? []) {
          subscriber.push(result.event);
        }
      }
      return result.event;
    });
  }

  subscribe(
    sessionId: string,
    options: { afterSequence?: number } = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    const afterSequence = options.afterSequence ?? 0;
    let bucket = this.subscribers.get(sessionId);
    if (bucket === undefined) {
      bucket = new Set();
      this.subscribers.set(sessionId, bucket);
    }
    const subscribers = bucket;
    const inner = new RingBufferSubscription<StoredKajiEvent>(
      this.subscriberCapacity,
      () => {
        subscribers.delete(inner);
        if (subscribers.size === 0) this.subscribers.delete(sessionId);
      },
      afterSequence,
    );
    const ready = this.serial.run(async () => {
      try {
        const backlog = await this.store.getEvents(sessionId, {
          afterSequence,
          limit: this.subscriberCapacity + 1,
        });
        if (backlog.length > this.subscriberCapacity) {
          throw new EventBufferOverflowError(
            afterSequence,
            await this.store.lastSequence(sessionId),
          );
        }
        if (!inner.isClosed) subscribers.add(inner);
        return { attached: true, backlog } as const;
      } catch (error) {
        inner.close();
        return { attached: false, error } as const;
      }
    });
    return new AttachedSubscription(inner, ready, afterSequence);
  }

  close(): void {
    for (const subscribers of this.subscribers.values()) {
      for (const subscriber of [...subscribers]) subscriber.close();
    }
    this.subscribers.clear();
  }
}

/** Experimental adapter for stores and buses that cannot share one atomic boundary. */
export class SplitEventCommitter implements EventCommitter {
  private readonly serial = new SerialExecutor();
  private readonly pending = new Map<string, StoredKajiEvent>();
  private readonly subscriberCapacity: number;
  readonly maxPendingEvents: number;

  constructor(
    readonly store: EventStore,
    readonly bus: EventBusProtocol<KajiEvent | StoredKajiEvent>,
    options: SplitEventCommitterOptions = {},
  ) {
    this.subscriberCapacity = options.subscriberCapacity ?? 1_024;
    this.maxPendingEvents = options.maxPendingEvents ?? 1_024;
    if (!Number.isInteger(this.subscriberCapacity) || this.subscriberCapacity <= 0) {
      throw new RangeError("subscriberCapacity must be a positive integer");
    }
    if (!Number.isInteger(this.maxPendingEvents) || this.maxPendingEvents <= 0) {
      throw new RangeError("maxPendingEvents must be a positive integer");
    }
  }

  commit(input: NewKajiEventType): Promise<StoredKajiEvent> {
    const event = NewKajiEvent.parse(input);
    return this.serial.run(() => this.commitUnlocked(event));
  }

  private async commitUnlocked(event: NewKajiEventType): Promise<StoredKajiEvent> {
    const pending = this.pending.get(event.id);
    if (pending !== undefined) {
      const { sequence: _, ...original } = pending;
      if (!structurallyEqualJson(original, event)) {
        throw new EventIdConflictError(event.id);
      }
      return this.publishPendingUnlocked(event.id);
    }
    if (this.pending.size >= this.maxPendingEvents) {
      throw new EventStoreCapacityError(
        event.session_id,
        `Pending delivery outbox reached its capacity of ${this.maxPendingEvents}; event ${event.id} was not persisted`,
      );
    }

    let result;
    try {
      result = await this.store.append(event);
    } catch (cause) {
      if (cause instanceof EventIdConflictError || cause instanceof EventStoreCapacityError) {
        throw cause;
      }
      throw new EventDeliveryError("append", event.id, false, { cause });
    }
    if (!result.inserted) return result.event;
    if (this.hasPendingForSession(result.event.session_id)) {
      this.pending.set(result.event.id, result.event);
      throw new EventDeliveryError("publish", result.event.id, true, {
        cause: new Error(
          `Event ${result.event.id} is queued behind an earlier pending event for session ${result.event.session_id}`,
        ),
      });
    }
    try {
      await this.bus.publish(result.event);
    } catch (cause) {
      this.pending.set(result.event.id, result.event);
      throw new EventDeliveryError("publish", result.event.id, true, { cause });
    }
    return result.event;
  }

  retryPublish(eventId: string): Promise<StoredKajiEvent> {
    return this.serial.run(() => this.publishPendingUnlocked(eventId));
  }

  private async publishPendingUnlocked(eventId: string): Promise<StoredKajiEvent> {
    const target = this.pending.get(eventId);
    if (target === undefined) throw new Error(`No pending event ${eventId}`);
    const required = [...this.pending.values()]
      .filter(
        (event) => event.session_id === target.session_id && event.sequence <= target.sequence,
      )
      .sort((left, right) => left.sequence - right.sequence);
    for (const event of required) {
      try {
        await this.bus.publish(event);
      } catch (cause) {
        throw new EventDeliveryError("publish", event.id, true, { cause });
      }
      this.pending.delete(event.id);
    }
    return target;
  }

  private hasPendingForSession(sessionId: string): boolean {
    for (const event of this.pending.values()) {
      if (event.session_id === sessionId) return true;
    }
    return false;
  }

  retry(eventId: string): Promise<StoredKajiEvent> {
    return this.retryPublish(eventId);
  }

  subscribe(
    sessionId: string,
    options: { afterSequence?: number } = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    const afterSequence = options.afterSequence ?? 0;
    const live = this.bus.subscribe(sessionId, { afterSequence });
    return new SplitSubscription(
      live,
      this.store,
      sessionId,
      this.subscriberCapacity,
      afterSequence,
    );
  }

  pendingEventIds(): string[] {
    return [...this.pending.keys()];
  }
}
