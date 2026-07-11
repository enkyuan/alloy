import { describe, expect, it } from "vitest";

import {
  EventBufferOverflowError,
  EventDeliveryError,
  EventIdConflictError,
  EventStoreCapacityError,
} from "@/events/errors";
import { InMemoryEventCommitter, SplitEventCommitter } from "@/events/committer";
import type { EventBusProtocol, EventBusSubscribeOptions } from "@/events/protocols";
import { KajiEvent, type StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore, type AppendResult } from "@/events/store";
import { EventType } from "@/events/types";
import type { MetricMeasurement, MetricsSink } from "@/observability";

function message(id: string, sessionId = "s1") {
  return KajiEvent.parse({ id, type: EventType.USER_MESSAGE, session_id: sessionId, content: id });
}

class CountingStore extends InMemoryEventStore {
  appendCalls = 0;
  failAppend = false;

  override async append(event: ReturnType<typeof message>): Promise<AppendResult> {
    this.appendCalls += 1;
    if (this.failAppend) throw new Error("append failed");
    return super.append(event);
  }
}

class FlakyBus implements EventBusProtocol<StoredKajiEvent> {
  failures = 0;
  readonly published: StoredKajiEvent[] = [];

  async publish(event: StoredKajiEvent): Promise<void> {
    if (this.failures > 0) {
      this.failures -= 1;
      throw new Error("publish failed");
    }
    this.published.push(event);
  }

  subscribe(
    _sessionId: string,
    _options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    return (async function* () {})();
  }

  close(): void {}
}

class BlockingFirstPublishBus extends FlakyBus {
  private publishCount = 0;
  private releaseFirst!: () => void;
  readonly firstPublishStarted: Promise<void>;
  private readonly firstPublishGate: Promise<void>;

  constructor() {
    super();
    let started!: () => void;
    this.firstPublishStarted = new Promise((resolve) => {
      started = resolve;
    });
    this.firstPublishGate = new Promise((resolve) => {
      this.releaseFirst = resolve;
    });
    this.markStarted = started;
  }

  private readonly markStarted: () => void;

  override async publish(event: StoredKajiEvent): Promise<void> {
    this.publishCount += 1;
    if (this.publishCount === 1) {
      this.markStarted();
      await this.firstPublishGate;
      throw new Error("first publish failed");
    }
    return super.publish(event);
  }

  failFirstPublish(): void {
    this.releaseFirst();
  }
}

class PagingStore extends InMemoryEventStore {
  readonly requests: Array<{ afterSequence?: number; limit?: number }> = [];

  override async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<StoredKajiEvent[]> {
    this.requests.push(options);
    return super.getEvents(sessionId, options);
  }
}

class FailingReadStore extends InMemoryEventStore {
  override async getEvents(): Promise<StoredKajiEvent[]> {
    throw new Error("read failed");
  }
}

class TrackingLiveBus extends FlakyBus {
  closedSubscriptions = 0;
  lastSubscribeOptions: EventBusSubscribeOptions | undefined;

  override subscribe(
    _sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    this.lastSubscribeOptions = options;
    const bus = this;
    return {
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      return: async () => {
        bus.closedSubscriptions += 1;
        return { value: undefined, done: true };
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
}

class OverflowingLiveBus extends TrackingLiveBus {
  override subscribe(
    _sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    const parent = super.subscribe(_sessionId, options);
    return {
      next: () => Promise.reject(new EventBufferOverflowError(0, 4)),
      return: () => parent.return!(),
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
}

class LazyCursorBackedBus implements EventBusProtocol<StoredKajiEvent> {
  readonly published: StoredKajiEvent[] = [];
  lastSubscribeOptions: EventBusSubscribeOptions | undefined;

  async publish(event: StoredKajiEvent): Promise<void> {
    this.published.push(event);
  }

  subscribe(
    sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    this.lastSubscribeOptions = options;
    const afterSequence = options.afterSequence ?? 0;
    const bus = this;
    return (async function* () {
      for (const event of bus.published) {
        if (event.session_id === sessionId && event.sequence > afterSequence) yield event;
      }
    })();
  }

  close(): void {}
}

describe("event delivery", () => {
  it("exposes and validates the split pending-delivery bound", () => {
    const store = new InMemoryEventStore();
    const bus = new FlakyBus();

    expect(new SplitEventCommitter(store, bus).maxPendingEvents).toBe(1_024);
    expect(() => new SplitEventCommitter(store, bus, { maxPendingEvents: 0 })).toThrow(
      /maxPendingEvents must be a positive integer/,
    );
  });

  it("joins backlog and live delivery without an attach gap", async () => {
    const committer = new InMemoryEventCommitter();
    await committer.commit(message("one"));
    const subscription = committer.subscribe("s1");
    const live = committer.commit(message("two"));

    expect((await subscription.next()).value?.id).toBe("one");
    await live;
    expect((await subscription.next()).value?.id).toBe("two");
    await subscription.return?.();
  });

  it("does not fan out an identical duplicate", async () => {
    const committer = new InMemoryEventCommitter();
    const subscription = committer.subscribe("s1");
    const event = message("duplicate");
    await committer.commit(event);
    expect((await subscription.next()).value?.id).toBe("duplicate");

    await committer.commit({ ...event });
    await committer.commit(message("next"));
    expect((await subscription.next()).value?.id).toBe("next");
    expect(await committer.store.lastSequence("s1")).toBe(2);
  });

  it("prevents subscriber payload mutation from corrupting persistence", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const subscription = committer.subscribe("s1");
    await committer.commit(
      KajiEvent.parse({
        id: "subscriber-immutable",
        type: EventType.USER_MESSAGE,
        session_id: "s1",
        content: "hello",
        metadata: { nested: { value: 1 } },
      }),
    );
    const delivered = (await subscription.next()).value!;

    expect(() => {
      (delivered.metadata.nested as { value: number }).value = 2;
    }).toThrow(TypeError);
    const [persisted] = await store.getEvents("s1");
    expect((persisted?.metadata.nested as { readonly value: number }).value).toBe(1);
    await subscription.return?.();
  });

  it("terminates only a lagging subscriber and resumes from its cursor", async () => {
    const committer = new InMemoryEventCommitter(new InMemoryEventStore(), {
      subscriberCapacity: 2,
    });
    await committer.commit(message("one"));
    const lagging = committer.subscribe("s1");
    expect((await lagging.next()).value?.sequence).toBe(1);
    const current = committer.subscribe("s1", { afterSequence: 1 });
    await committer.commit(message("two"));
    expect((await current.next()).value?.sequence).toBe(2);
    await committer.commit(message("three"));
    expect((await current.next()).value?.sequence).toBe(3);
    await committer.commit(message("four"));
    expect((await current.next()).value?.sequence).toBe(4);

    await expect(lagging.next()).rejects.toMatchObject({
      code: "EVENT_BUFFER_OVERFLOW",
      lastSequence: 1,
      latestSequence: 4,
    } satisfies Partial<EventBufferOverflowError>);

    const missed = await committer.store.getEvents("s1", { afterSequence: 1, limit: 1 });
    expect(missed.map(({ sequence }) => sequence)).toEqual([2]);
    const resumed = committer.subscribe("s1", { afterSequence: 2 });
    const replayed = [await resumed.next(), await resumed.next()];
    expect(replayed.map(({ value }) => value?.sequence)).toEqual([3, 4]);
    await current.return?.();
    await resumed.return?.();
  });

  it("serves a captured stable backlog after its closed session is evicted", async () => {
    const store = new InMemoryEventStore({ maxSessions: 1 });
    const committer = new InMemoryEventCommitter(store);
    await committer.commit(
      KajiEvent.parse({ id: "closed", type: EventType.SESSION_CLOSED, session_id: "closed" }),
    );
    const subscription = committer.subscribe("closed");

    await committer.commit(message("new-session", "new"));

    expect(await store.getEvents("closed")).toEqual([]);
    expect((await subscription.next()).value?.id).toBe("closed");
    await subscription.return?.();
  });

  it("closes a stable subscriber when its bounded backlog read fails", async () => {
    const committer = new InMemoryEventCommitter(new FailingReadStore());
    const subscription = committer.subscribe("s1");

    await expect(subscription.next()).rejects.toThrow("read failed");
    const subscribers = (
      committer as unknown as {
        subscribers: Map<string, Set<unknown>>;
      }
    ).subscribers;
    expect(subscribers.size).toBe(0);
  });

  it("keeps a stable subscription closed when returned before attachment finishes", async () => {
    const committer = new InMemoryEventCommitter();
    const subscription = committer.subscribe("s1");

    await subscription.return?.();
    await committer.commit(message("after-return"));

    expect((await subscription.next()).done).toBe(true);
    const subscribers = (
      committer as unknown as {
        subscribers: Map<string, Set<unknown>>;
      }
    ).subscribers;
    expect(subscribers.size).toBe(0);
  });

  it("bounds the stable backlog snapshot before attaching live delivery", async () => {
    const store = new PagingStore();
    for (let index = 1; index <= 3; index++) {
      await store.append(message(`stable-backlog-${index}`));
    }
    const committer = new InMemoryEventCommitter(store, { subscriberCapacity: 2 });
    const subscription = committer.subscribe("s1");

    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_BUFFER_OVERFLOW",
      lastSequence: 0,
      latestSequence: 3,
    } satisfies Partial<EventBufferOverflowError>);
    expect(store.requests[0]).toEqual({ afterSequence: 0, limit: 3 });
  });

  it("reports append failure as not persisted and publishes nothing", async () => {
    const store = new CountingStore();
    store.failAppend = true;
    const bus = new FlakyBus();
    const committer = new SplitEventCommitter(store, bus);

    await expect(committer.commit(message("append-failure"))).rejects.toMatchObject({
      phase: "append",
      eventId: "append-failure",
      persisted: false,
    } satisfies Partial<EventDeliveryError>);
    expect(bus.published).toEqual([]);
  });

  it("retries publish without appending the event twice", async () => {
    const store = new CountingStore();
    const bus = new FlakyBus();
    bus.failures = 1;
    const committer = new SplitEventCommitter(store, bus);

    await expect(committer.commit(message("publish-failure"))).rejects.toMatchObject({
      phase: "publish",
      eventId: "publish-failure",
      persisted: true,
    } satisfies Partial<EventDeliveryError>);
    const retried = await committer.retryPublish("publish-failure");

    expect(retried.sequence).toBe(1);
    expect(store.appendCalls).toBe(1);
    expect(bus.published.map(({ id }) => id)).toEqual(["publish-failure"]);
    expect(committer.pendingEventIds()).toEqual([]);
  });

  it("queues later session events and drains prerequisites in sequence order", async () => {
    const store = new CountingStore();
    const bus = new FlakyBus();
    bus.failures = 1;
    const committer = new SplitEventCommitter(store, bus);

    await expect(committer.commit(message("a"))).rejects.toMatchObject({
      eventId: "a",
      persisted: true,
    } satisfies Partial<EventDeliveryError>);
    await expect(committer.commit(message("b"))).rejects.toMatchObject({
      eventId: "b",
      persisted: true,
    } satisfies Partial<EventDeliveryError>);

    expect(bus.published).toEqual([]);
    expect(committer.pendingEventIds()).toEqual(["a", "b"]);
    await expect(committer.retryPublish("b")).resolves.toMatchObject({ id: "b", sequence: 2 });
    expect(bus.published.map(({ id }) => id)).toEqual(["a", "b"]);
    expect(committer.pendingEventIds()).toEqual([]);
    expect(store.appendCalls).toBe(2);
  });

  it("applies outbox backpressure before appending beyond the configured cap", async () => {
    const store = new CountingStore();
    const bus = new FlakyBus();
    bus.failures = 10;
    const committer = new SplitEventCommitter(store, bus, { maxPendingEvents: 2 });

    await expect(committer.commit(message("a"))).rejects.toBeInstanceOf(EventDeliveryError);
    await expect(committer.commit(message("b"))).rejects.toBeInstanceOf(EventDeliveryError);
    await expect(committer.commit(message("c"))).rejects.toMatchObject({
      code: "EVENT_STORE_CAPACITY_EXCEEDED",
      sessionId: "s1",
      message: expect.stringMatching(/pending delivery outbox.*2.*not persisted/i),
    } satisfies Partial<EventStoreCapacityError>);

    expect(store.appendCalls).toBe(2);
    expect(await store.lastSequence("s1")).toBe(2);
    expect(committer.pendingEventIds()).toEqual(["a", "b"]);
  });

  it("deduplicates a pending retry with reordered nested keys", async () => {
    const store = new CountingStore();
    const bus = new FlakyBus();
    bus.failures = 1;
    const committer = new SplitEventCommitter(store, bus);
    const original = KajiEvent.parse({
      id: "nested",
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "s1",
      turn_id: "turn-1",
      tool_name: "search",
      tool_call_id: "call-1",
      tool_args: { filters: { a: 1, b: 2 } },
    });
    await expect(committer.commit(original)).rejects.toBeInstanceOf(EventDeliveryError);

    const reordered = KajiEvent.parse({
      ...original,
      tool_args: { filters: { b: 2, a: 1 } },
    });
    await expect(committer.commit(reordered)).resolves.toMatchObject({ id: "nested", sequence: 1 });
    expect(store.appendCalls).toBe(1);
    expect(bus.published.map(({ id }) => id)).toEqual(["nested"]);
  });

  it("records a pending event-id structural conflict as an append failure", async () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const store = new CountingStore();
    const bus = new FlakyBus();
    bus.failures = 1;
    const committer = new SplitEventCommitter(store, bus, { metricsSink: metrics });
    await expect(committer.commit(message("conflict"))).rejects.toBeInstanceOf(EventDeliveryError);

    await expect(
      committer.commit(
        KajiEvent.parse({
          id: "conflict",
          type: EventType.USER_MESSAGE,
          session_id: "s1",
          content: "different",
        }),
      ),
    ).rejects.toBeInstanceOf(EventIdConflictError);

    expect(
      measurements.filter(
        (measurement) =>
          measurement.name === "kaji.journal.failures" && measurement.labels.stage === "append",
      ),
    ).toHaveLength(1);
    expect(store.appendCalls).toBe(1);
  });

  it("serializes a concurrent duplicate behind the first publish result", async () => {
    const store = new CountingStore();
    const bus = new BlockingFirstPublishBus();
    const committer = new SplitEventCommitter(store, bus);
    const event = message("concurrent-duplicate");

    const first = committer.commit(event);
    const firstFailure = expect(first).rejects.toMatchObject({
      phase: "publish",
      persisted: true,
    });
    await bus.firstPublishStarted;
    let secondSettled = false;
    const second = committer.commit({ ...event }).then((stored) => {
      secondSettled = true;
      return stored;
    });
    await Promise.resolve();
    expect(secondSettled).toBe(false);

    bus.failFirstPublish();
    await firstFailure;
    await expect(second).resolves.toMatchObject({ id: event.id, sequence: 1 });
    expect(store.appendCalls).toBe(1);
    expect(bus.published.map(({ id }) => id)).toEqual([event.id]);
  });

  it("bounds split backlog reads and closes live delivery on overflow", async () => {
    const store = new PagingStore();
    for (let index = 1; index <= 4; index++) {
      await store.append(message(`backlog-${index}`));
    }
    const bus = new TrackingLiveBus();
    const committer = new SplitEventCommitter(store, bus, { subscriberCapacity: 2 });
    const subscription = committer.subscribe("s1", { afterSequence: 1 });

    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_BUFFER_OVERFLOW",
      lastSequence: 1,
      latestSequence: 4,
    } satisfies Partial<EventBufferOverflowError>);
    expect(store.requests[0]).toEqual({ afterSequence: 1, limit: 3 });
    expect(bus.lastSubscribeOptions).toEqual({ afterSequence: 1 });
    expect(bus.closedSubscriptions).toBe(1);
  });

  it("accepts a lazy cursor-backed bus without losing the backlog-live boundary", async () => {
    const store = new InMemoryEventStore();
    const bus = new LazyCursorBackedBus();
    const committer = new SplitEventCommitter(store, bus);
    await committer.commit(message("one"));
    const subscription = committer.subscribe("s1", { afterSequence: 0 });

    expect((await subscription.next()).value?.id).toBe("one");
    await committer.commit(message("two"));
    expect((await subscription.next()).value?.id).toBe("two");
    expect(bus.lastSubscribeOptions).toEqual({ afterSequence: 0 });
    await subscription.return?.();
  });

  it("closes eager split delivery when returned before the first next call", async () => {
    const bus = new TrackingLiveBus();
    const committer = new SplitEventCommitter(new InMemoryEventStore(), bus);
    const subscription = committer.subscribe("s1");

    await subscription.return?.();

    expect(bus.closedSubscriptions).toBe(1);
  });

  it("closes eager split delivery when the backlog read fails", async () => {
    const bus = new TrackingLiveBus();
    const committer = new SplitEventCommitter(new FailingReadStore(), bus);
    const subscription = committer.subscribe("s1");

    await expect(subscription.next()).rejects.toThrow("read failed");

    expect(bus.closedSubscriptions).toBe(1);
  });

  it("translates live overflow to the delivered backlog cursor", async () => {
    const store = new InMemoryEventStore();
    await store.append(message("backlog-one"));
    await store.append(message("backlog-two"));
    const bus = new OverflowingLiveBus();
    const committer = new SplitEventCommitter(store, bus);
    const subscription = committer.subscribe("s1");

    expect((await subscription.next()).value?.sequence).toBe(1);
    expect((await subscription.next()).value?.sequence).toBe(2);
    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_BUFFER_OVERFLOW",
      lastSequence: 2,
      latestSequence: 4,
    } satisfies Partial<EventBufferOverflowError>);
    expect(bus.closedSubscriptions).toBe(1);
  });
});
