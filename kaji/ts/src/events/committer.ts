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
  type NewKajiEvent as NewKajiEventType,
  type StoredKajiEvent,
  snapshotNewEvent,
  validateStoredEvent,
} from "@/events/schemas";
import {
  type EventStore,
  type EventStoreSession,
  InMemoryEventStore,
  type SessionEventListener,
  supportsSessionTransactions,
} from "@/events/store";
import { NOOP_METRICS, recordMetric, type MetricsSink } from "@/observability";

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
  private detached = false;

  constructor(
    private readonly inner: RingBufferSubscription<StoredKajiEvent>,
    private readonly ready: Promise<
      | { readonly attached: true; readonly backlog: readonly StoredKajiEvent[] }
      | { readonly attached: false; readonly error: unknown }
    >,
    afterSequence: number,
    private readonly detach: () => Promise<void>,
    private readonly onClose: () => void,
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
      if (next.done) await this.close();
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
    if (!this.closed) {
      this.closed = true;
      await this.inner.return();
    }
    if (this.detached) return;
    this.detached = true;
    try {
      await this.ready;
      await this.detach();
    } finally {
      this.onClose();
    }
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
    private readonly metrics: MetricsSink,
    private readonly readyBacklog?: Promise<
      | { readonly ready: true; readonly backlog: readonly StoredKajiEvent[] }
      | { readonly ready: false; readonly error: unknown }
    >,
  ) {
    this.cursor = afterSequence;
  }

  async next(): Promise<IteratorResult<StoredKajiEvent>> {
    if (this.closed) return { value: undefined, done: true };
    try {
      if (this.backlog === undefined) {
        if (this.readyBacklog !== undefined) {
          const result = await this.readyBacklog;
          if (!result.ready) throw result.error;
          this.backlog = result.backlog;
        } else {
          const backlog = (
            await this.store.getEvents(this.sessionId, {
              afterSequence: this.cursor,
              limit: this.subscriberCapacity + 1,
            })
          ).map(validateStoredEvent);
          recordMetric(this.metrics, "kaji.subscriber.lag_events", backlog.length, {});
          if (backlog.length > this.subscriberCapacity) {
            recordMetric(this.metrics, "kaji.subscriber.overflow", 1, { stage: "lag" });
            throw new EventBufferOverflowError(
              this.cursor,
              await this.store.lastSequence(this.sessionId),
            );
          }
          this.backlog = backlog;
        }
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
        const event = validateStoredEvent(candidate.value);
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
  metricsSink?: MetricsSink;
}

export interface SplitEventCommitterOptions {
  subscriberCapacity?: number;
  maxPendingEvents?: number;
  metricsSink?: MetricsSink;
}

interface PendingSlot {
  active: boolean;
}

/** Stable single-process append + fanout boundary. */
export class InMemoryEventCommitter implements EventCommitter {
  private readonly serial = new SerialExecutor();
  private readonly subscribers = new Map<string, Set<RingBufferSubscription<StoredKajiEvent>>>();
  private readonly subscriberCapacity: number;
  private readonly metrics: MetricsSink;
  private readonly transactionalStore;
  private readonly subscriptions = new Set<AttachedSubscription>();

  constructor(
    readonly store: EventStore = new InMemoryEventStore(),
    options: InMemoryEventCommitterOptions = {},
  ) {
    this.subscriberCapacity = options.subscriberCapacity ?? 1_024;
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.transactionalStore = supportsSessionTransactions(store) ? store : undefined;
    if (!Number.isInteger(this.subscriberCapacity) || this.subscriberCapacity <= 0) {
      throw new RangeError("subscriberCapacity must be a positive integer");
    }
  }

  commit(event: NewKajiEventType): Promise<StoredKajiEvent> {
    const validated = snapshotNewEvent(event);
    if (this.transactionalStore !== undefined) {
      return this.transactionalStore.sessionTransaction(validated.session_id, (transaction) =>
        this.commitWith(validated, transaction),
      );
    }
    return this.serial.run(() => this.commitWith(validated));
  }

  private async commitWith(
    validated: NewKajiEventType,
    transaction?: EventStoreSession,
  ): Promise<StoredKajiEvent> {
    let result;
    try {
      result =
        transaction === undefined
          ? await this.store.append(validated)
          : await transaction.appendLocked(validated);
    } catch (cause) {
      recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "append" });
      if (cause instanceof EventIdConflictError || cause instanceof EventStoreCapacityError) {
        throw cause;
      }
      throw new EventDeliveryError("append", validated.id, false, { cause });
    }
    const stored = transaction === undefined ? validateStoredEvent(result.event) : result.event;
    if (result.inserted && transaction === undefined) {
      for (const subscriber of this.subscribers.get(stored.session_id) ?? []) {
        subscriber.push(stored);
      }
    }
    return stored;
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
      this.metrics,
    );
    let listener: SessionEventListener | undefined;
    const attach = async (transaction?: EventStoreSession) => {
      try {
        const backlog = (
          transaction === undefined
            ? await this.store.getEvents(sessionId, {
                afterSequence,
                limit: this.subscriberCapacity + 1,
              })
            : transaction.getEventsLocked({
                afterSequence,
                limit: this.subscriberCapacity + 1,
              })
        ).map(validateStoredEvent);
        recordMetric(this.metrics, "kaji.subscriber.lag_events", backlog.length, {});
        if (backlog.length > this.subscriberCapacity) {
          recordMetric(this.metrics, "kaji.subscriber.overflow", 1, { stage: "lag" });
          throw new EventBufferOverflowError(
            afterSequence,
            transaction === undefined
              ? await this.store.lastSequence(sessionId)
              : transaction.lastSequenceLocked(),
          );
        }
        if (!inner.isClosed) {
          subscribers.add(inner);
          if (transaction !== undefined) {
            listener = (event) => {
              inner.push(event);
              return !inner.isClosed;
            };
            transaction.attachListenerLocked(listener);
          }
        }
        return { attached: true, backlog } as const;
      } catch (error) {
        inner.close();
        return { attached: false, error } as const;
      }
    };
    const ready =
      this.transactionalStore === undefined
        ? this.serial.run(() => attach())
        : this.transactionalStore.sessionTransaction(sessionId, attach);
    const detach = async () => {
      if (this.transactionalStore === undefined || listener === undefined) return;
      await this.transactionalStore.sessionTransaction(sessionId, async (transaction) => {
        transaction.detachListenerLocked(listener!);
      });
    };
    const subscription = new AttachedSubscription(inner, ready, afterSequence, detach, () =>
      this.subscriptions.delete(subscription),
    );
    this.subscriptions.add(subscription);
    return subscription;
  }

  async close(): Promise<void> {
    await Promise.all([...this.subscriptions].map((subscription) => subscription.return()));
    this.subscriptions.clear();
    this.subscribers.clear();
  }
}

/** Experimental adapter for stores and buses that cannot share one atomic boundary. */
export class SplitEventCommitter implements EventCommitter {
  private readonly serial = new SerialExecutor();
  private readonly pending = new Map<string, StoredKajiEvent>();
  private readonly subscriberCapacity: number;
  private readonly metrics: MetricsSink;
  private readonly transactionalStore;
  private pendingReservations = 0;
  readonly maxPendingEvents: number;

  constructor(
    readonly store: EventStore,
    readonly bus: EventBusProtocol<KajiEvent | StoredKajiEvent>,
    options: SplitEventCommitterOptions = {},
  ) {
    this.subscriberCapacity = options.subscriberCapacity ?? 1_024;
    this.metrics = options.metricsSink ?? NOOP_METRICS;
    this.transactionalStore = supportsSessionTransactions(store) ? store : undefined;
    this.maxPendingEvents = options.maxPendingEvents ?? 1_024;
    if (!Number.isInteger(this.subscriberCapacity) || this.subscriberCapacity <= 0) {
      throw new RangeError("subscriberCapacity must be a positive integer");
    }
    if (!Number.isInteger(this.maxPendingEvents) || this.maxPendingEvents <= 0) {
      throw new RangeError("maxPendingEvents must be a positive integer");
    }
  }

  commit(input: NewKajiEventType): Promise<StoredKajiEvent> {
    const event = snapshotNewEvent(input);
    let slot: PendingSlot;
    try {
      slot = this.reservePendingSlot(event);
    } catch (error) {
      return Promise.reject(error);
    }
    const operation = (transaction?: EventStoreSession) =>
      this.commitUnlocked(event, slot, transaction);
    const result =
      this.transactionalStore !== undefined
        ? this.transactionalStore.sessionTransaction(event.session_id, operation)
        : this.serial.run(() => operation());
    return result.finally(() => this.releasePendingSlot(slot));
  }

  private reservePendingSlot(event: NewKajiEventType): PendingSlot {
    const pending = this.pending.get(event.id);
    if (pending !== undefined) {
      const { sequence: _, ...original } = pending;
      if (!structurallyEqualJson(original, event)) {
        recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "append" });
        throw new EventIdConflictError(event.id);
      }
      return { active: false };
    }
    if (this.pending.size + this.pendingReservations >= this.maxPendingEvents) {
      recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "append" });
      throw new EventStoreCapacityError(
        event.session_id,
        `Pending delivery outbox reached its capacity of ${this.maxPendingEvents}; event ${event.id} was not persisted`,
      );
    }
    this.pendingReservations += 1;
    return { active: true };
  }

  private releasePendingSlot(slot: PendingSlot): void {
    if (!slot.active) return;
    this.pendingReservations -= 1;
    slot.active = false;
  }

  private promotePendingSlot(slot: PendingSlot, event: StoredKajiEvent): void {
    this.pending.set(event.id, event);
    this.releasePendingSlot(slot);
  }

  private async commitUnlocked(
    event: NewKajiEventType,
    slot: PendingSlot,
    transaction?: EventStoreSession,
  ): Promise<StoredKajiEvent> {
    if (this.pending.has(event.id)) return this.publishPendingUnlocked(event.id);

    let result;
    try {
      result =
        transaction === undefined
          ? await this.store.append(event)
          : await transaction.appendLocked(event);
    } catch (cause) {
      recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "append" });
      if (cause instanceof EventIdConflictError || cause instanceof EventStoreCapacityError) {
        throw cause;
      }
      throw new EventDeliveryError("append", event.id, false, { cause });
    }
    const stored = transaction === undefined ? validateStoredEvent(result.event) : result.event;
    if (!result.inserted) return stored;
    if (this.hasPendingForSession(stored.session_id)) {
      this.promotePendingSlot(slot, stored);
      recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "publish" });
      throw new EventDeliveryError("publish", stored.id, true, {
        cause: new Error(
          `Event ${stored.id} is queued behind an earlier pending event for session ${stored.session_id}`,
        ),
      });
    }
    try {
      await this.bus.publish(stored);
    } catch (cause) {
      this.promotePendingSlot(slot, stored);
      recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "publish" });
      throw new EventDeliveryError("publish", stored.id, true, { cause });
    }
    return stored;
  }

  retryPublish(eventId: string): Promise<StoredKajiEvent> {
    const event = this.pending.get(eventId);
    if (event === undefined) return Promise.reject(new Error(`No pending event ${eventId}`));
    if (this.transactionalStore !== undefined) {
      return this.transactionalStore.sessionTransaction(event.session_id, () =>
        this.publishPendingUnlocked(eventId),
      );
    }
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
        recordMetric(this.metrics, "kaji.journal.failures", 1, { stage: "publish" });
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
    const readyBacklog = this.transactionalStore
      ?.sessionTransaction(sessionId, async (transaction) => {
        const backlog = transaction
          .getEventsLocked({
            afterSequence,
            limit: this.subscriberCapacity + 1,
          })
          .map(validateStoredEvent);
        recordMetric(this.metrics, "kaji.subscriber.lag_events", backlog.length, {});
        if (backlog.length > this.subscriberCapacity) {
          recordMetric(this.metrics, "kaji.subscriber.overflow", 1, { stage: "lag" });
          throw new EventBufferOverflowError(afterSequence, transaction.lastSequenceLocked());
        }
        return backlog;
      })
      .then(
        (backlog) => ({ ready: true, backlog }) as const,
        (error: unknown) => ({ ready: false, error }) as const,
      );
    return new SplitSubscription(
      live,
      this.store,
      sessionId,
      this.subscriberCapacity,
      afterSequence,
      this.metrics,
      readyBacklog,
    );
  }

  pendingEventIds(): string[] {
    return [...this.pending.keys()];
  }
}
