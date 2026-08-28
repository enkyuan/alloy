import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";

import {
  EventBufferOverflowError,
  EventDeliveryError,
  EventIdConflictError,
  EventSchemaIncompatibleError,
  EventStoreCapacityError,
  SessionPurgeBusyError,
  SessionPurgeUnsupportedError,
} from "@/events/errors";
import { InMemoryEventCommitter, SplitEventCommitter } from "@/events/committer";
import { EventBus } from "@/events/bus";
import type { EventBusProtocol, EventBusSubscribeOptions } from "@/events/protocols";
import { KajiEvent, type NewKajiEvent, type StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore, type AppendResult, type EventStoreSession } from "@/events/store";
import {
  coordinatedSessionPurge,
  type SessionPurgeAuthorization,
} from "@/events/session-lifecycle";
import { EventType } from "@/events/types";
import type { MetricMeasurement, MetricsSink } from "@/observability";

function message(id: string, sessionId = "s1") {
  return KajiEvent.parse({ id, type: EventType.USER_MESSAGE, session_id: sessionId, content: id });
}

function storedToolResultAccessor(id: string, onRead: () => void): Record<string, unknown> {
  const row: Record<string, unknown> = {
    ...KajiEvent.parse({
      id,
      type: EventType.TOOL_CALL_COMPLETED,
      session_id: "s1",
      turn_id: "turn-1",
      tool_name: "tool",
      tool_call_id: "call-1",
      result: {},
    }),
    sequence: 8,
  };
  Object.defineProperty(row, "result", {
    enumerable: true,
    get() {
      onRead();
      return { secret: "sk-custom-store-accessor" };
    },
  });
  return row;
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

class NonTransactionalStore extends InMemoryEventStore {
  override get sessionTransactionsEnabled(): boolean {
    return false;
  }
}

class SyncThrowTransactionStore extends InMemoryEventStore {
  override sessionTransaction<T>(
    _sessionId: string,
    _operation: (transaction: EventStoreSession) => Promise<T>,
  ): Promise<T> {
    throw new Error("transaction setup failed");
  }
}

class BlockingInsertStore extends InMemoryEventStore {
  readonly entered: Promise<void>;
  private enter!: () => void;
  private readonly release: Promise<void>;
  private unblock!: () => void;

  constructor() {
    super();
    this.entered = new Promise((resolve) => {
      this.enter = resolve;
    });
    this.release = new Promise((resolve) => {
      this.unblock = resolve;
    });
  }

  releaseBlocked(): void {
    this.unblock();
  }

  protected override async insertReserved(event: NewKajiEvent): Promise<AppendResult> {
    if (event.session_id === "blocked") {
      this.enter();
      await this.release;
    }
    return super.insertReserved(event);
  }
}

class PausedPurgeStore extends InMemoryEventStore {
  readonly purgeEntered = Promise.withResolvers<void>();
  private readonly purgeRelease = Promise.withResolvers<void>();

  releasePurge(): void {
    this.purgeRelease.resolve();
  }

  override async [coordinatedSessionPurge](
    sessionId: string,
    authorization: SessionPurgeAuthorization,
  ): Promise<boolean> {
    this.purgeEntered.resolve();
    await this.purgeRelease.promise;
    return super[coordinatedSessionPurge](sessionId, authorization);
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

class RawBacklogStore extends InMemoryEventStore {
  constructor(private readonly row: Record<string, unknown>) {
    super();
  }

  override async getEvents(): Promise<StoredKajiEvent[]> {
    return [this.row as unknown as StoredKajiEvent];
  }

  override async lastSequence(): Promise<number> {
    return this.row.sequence as number;
  }
}

class RawAppendStore extends InMemoryEventStore {
  constructor(private readonly row: Record<string, unknown>) {
    super();
  }

  override async append(): Promise<AppendResult> {
    return { event: this.row as unknown as StoredKajiEvent, inserted: true };
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
    return {
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      return: async () => {
        this.closedSubscriptions += 1;
        return { value: undefined, done: true };
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
}

class ReentrantSubscribeBus extends FlakyBus {
  onSubscribe: (() => void) | undefined;

  override subscribe(
    sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    this.onSubscribe?.();
    return super.subscribe(sessionId, options);
  }
}

class BlockingReturnBus extends FlakyBus {
  readonly returnEntered = Promise.withResolvers<void>();
  private readonly returnRelease = Promise.withResolvers<void>();
  returnCalls = 0;

  releaseReturn(): void {
    this.returnRelease.resolve();
  }

  override subscribe(): AsyncIterableIterator<StoredKajiEvent> {
    return {
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      return: async () => {
        this.returnCalls += 1;
        this.returnEntered.resolve();
        await this.returnRelease.promise;
        return { value: undefined, done: true };
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
}

class RetryableReturnBus extends FlakyBus {
  returnCalls = 0;

  override subscribe(): AsyncIterableIterator<StoredKajiEvent> {
    return {
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      return: async () => {
        this.returnCalls += 1;
        if (this.returnCalls === 1) throw new Error("return unavailable");
        return { value: undefined, done: true };
      },
      [Symbol.asyncIterator]() {
        return this;
      },
    };
  }
}

type MalformedLiveCandidateFactory = (
  teardown: () => Promise<IteratorResult<StoredKajiEvent>>,
) => unknown;

const MALFORMED_LIVE_CANDIDATES: readonly {
  readonly name: string;
  readonly candidateFactory: MalformedLiveCandidateFactory;
  readonly recoverable: boolean;
  readonly errorPattern: RegExp;
}[] = [
  {
    name: "a null candidate",
    candidateFactory: () => null,
    recoverable: false,
    errorPattern: /object/i,
  },
  {
    name: "a candidate without next",
    candidateFactory: (teardown) => ({
      return: teardown,
      [Symbol.asyncIterator]() {
        return this;
      },
    }),
    recoverable: true,
    errorPattern: /next/i,
  },
  {
    name: "a candidate without return",
    candidateFactory: () => ({
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      [Symbol.asyncIterator]() {
        return this;
      },
    }),
    recoverable: false,
    errorPattern: /return/i,
  },
  {
    name: "a candidate without Symbol.asyncIterator",
    candidateFactory: (teardown) => ({
      next: () => new Promise<IteratorResult<StoredKajiEvent>>(() => undefined),
      return: teardown,
    }),
    recoverable: true,
    errorPattern: /Symbol\.asyncIterator/i,
  },
];

class MalformedLiveBus extends FlakyBus {
  activeSubscriptions = 0;
  returnCalls = 0;

  constructor(private readonly candidateFactory: MalformedLiveCandidateFactory) {
    super();
  }

  override subscribe(): AsyncIterableIterator<StoredKajiEvent> {
    this.activeSubscriptions += 1;
    const teardown = async (): Promise<IteratorResult<StoredKajiEvent>> => {
      this.returnCalls += 1;
      this.activeSubscriptions -= 1;
      return { value: undefined, done: true };
    };
    return this.candidateFactory(teardown) as AsyncIterableIterator<StoredKajiEvent>;
  }
}

class SchemaErrorRetryableReturnBus extends FlakyBus {
  activeSubscriptions = 0;
  returnCalls = 0;

  constructor(private readonly row: Record<string, unknown>) {
    super();
  }

  override subscribe(): AsyncIterableIterator<StoredKajiEvent> {
    this.activeSubscriptions += 1;
    let delivered = false;
    return {
      next: async () => {
        if (delivered) return new Promise<IteratorResult<StoredKajiEvent>>(() => undefined);
        delivered = true;
        return { value: this.row as unknown as StoredKajiEvent, done: false };
      },
      return: async () => {
        this.returnCalls += 1;
        if (this.returnCalls === 1) throw new Error("return unavailable");
        this.activeSubscriptions -= 1;
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

class RawLiveBus extends TrackingLiveBus {
  constructor(private readonly row: Record<string, unknown>) {
    super();
  }

  override subscribe(
    _sessionId: string,
    options: EventBusSubscribeOptions = {},
  ): AsyncIterableIterator<StoredKajiEvent> {
    const parent = super.subscribe(_sessionId, options);
    let delivered = false;
    return {
      next: async () => {
        if (delivered) return new Promise<IteratorResult<StoredKajiEvent>>(() => undefined);
        delivered = true;
        return { value: this.row as unknown as StoredKajiEvent, done: false };
      },
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
    return async function* (this: LazyCursorBackedBus) {
      for (const event of this.published) {
        if (event.session_id === sessionId && event.sequence > afterSequence) yield event;
      }
    }.call(this);
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

  it("fans out shared-store commits from another committer and direct appends", async () => {
    const store = new InMemoryEventStore();
    const reader = new InMemoryEventCommitter(store);
    const writer = new InMemoryEventCommitter(store);
    const subscription = reader.subscribe("shared");

    const throughWriter = await writer.commit(message("writer", "shared"));
    const throughStore = await store.append(message("direct", "shared"));

    expect((await subscription.next()).value).toEqual(throughWriter);
    expect((await subscription.next()).value).toEqual(throughStore.event);
    await subscription.return?.();
    expect(store.activeSessionLaneCount).toBe(0);
    expect(store.activeListenerCount).toBe(0);
  });

  it("does not serialize stable commits for unrelated sessions", async () => {
    const store = new BlockingInsertStore();
    const committer = new InMemoryEventCommitter(store);
    const blocked = committer.commit(message("blocked", "blocked"));
    await store.entered;

    await expect(committer.commit(message("free", "free"))).resolves.toMatchObject({
      sequence: 1,
    });
    store.releaseBlocked();
    await expect(blocked).resolves.toMatchObject({ sequence: 1 });
    expect(store.activeSessionLaneCount).toBe(0);
  });

  it("does not let a queued same-session commit overtake fanout", async () => {
    const store = new BlockingInsertStore();
    const committer = new InMemoryEventCommitter(store);
    const subscription = committer.subscribe("blocked");
    const first = committer.commit(message("first", "blocked"));
    await store.entered;
    const second = committer.commit(message("second", "blocked"));

    store.releaseBlocked();
    const stored = await Promise.all([first, second]);
    expect([(await subscription.next()).value, (await subscription.next()).value]).toEqual(stored);
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
    expect((persisted!.metadata.nested as { readonly value: number }).value).toBe(1);
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

  it("retains a closed generation until its subscriber closes and purge is explicit", async () => {
    const store = new InMemoryEventStore({ maxSessions: 1 });
    const committer = new InMemoryEventCommitter(store);
    await committer.commit(
      KajiEvent.parse({ id: "closed", type: EventType.SESSION_CLOSED, session_id: "closed" }),
    );
    const subscription = committer.subscribe("closed");
    const captured = await subscription.next();

    await expect(committer.commit(message("new-session", "new"))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );

    expect((await store.getEvents("closed")).map(({ id }) => id)).toEqual(["closed"]);
    expect(captured.value?.id).toBe("closed");
    await subscription.return?.();
    await expect(store.purgeSession("closed")).resolves.toBe(true);
    await expect(committer.commit(message("new-session", "new"))).resolves.toMatchObject({
      sequence: 1,
    });
  });

  it("wakes a pending stable subscriber before direct purge can reuse its generation", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    await committer.commit(message("old", "generation"));
    const subscription = committer.subscribe("generation");
    await expect(subscription.next()).resolves.toMatchObject({
      done: false,
      value: { id: "old", sequence: 1 },
    });
    const waiting = subscription.next();

    await expect(store.purgeSession("generation")).rejects.toBeInstanceOf(SessionPurgeBusyError);
    expect((await store.getEvents("generation")).map(({ id }) => id)).toEqual(["old"]);
    await subscription.return?.();
    await expect(waiting).resolves.toEqual({ value: undefined, done: true });
    await expect(store.purgeSession("generation")).resolves.toBe(true);
  });

  it("keeps a close handle retryable when it races a direct purge fence", async () => {
    const store = new PausedPurgeStore();
    const committer = new InMemoryEventCommitter(store);
    await committer.commit(message("old", "close-race"));
    const subscription = committer.subscribe("close-race");
    await subscription.next();

    const purge = store.purgeSession("close-race");
    await store.purgeEntered.promise;
    await expect(subscription.return?.()).rejects.toBeInstanceOf(SessionPurgeBusyError);
    store.releasePurge();
    await expect(purge).rejects.toBeInstanceOf(SessionPurgeBusyError);

    await expect(subscription.return?.()).resolves.toEqual({ value: undefined, done: true });
    await expect(store.purgeSession("close-race")).resolves.toBe(true);
  });

  it("blocks split outbox purge until pending delivery is retried and disposed", async () => {
    const store = new InMemoryEventStore();
    const bus = new FlakyBus();
    bus.failures = 1;
    const committer = new SplitEventCommitter(store, bus);

    await expect(committer.commit(message("pending-old", "split-generation"))).rejects.toThrow(
      EventDeliveryError,
    );
    expect(committer.pendingEventIds()).toEqual(["pending-old"]);
    expect(() => committer.close()).toThrow(/pending/i);
    await expect(store.purgeSession("split-generation")).rejects.toMatchObject({
      code: "SESSION_PURGE_UNSUPPORTED",
      component: "event_delivery",
    } satisfies Partial<SessionPurgeUnsupportedError>);
    expect((await store.getEvents("split-generation")).map(({ id }) => id)).toEqual([
      "pending-old",
    ]);

    await expect(committer.retryPublish("pending-old")).resolves.toMatchObject({ sequence: 1 });
    expect(bus.published.map(({ id }) => id)).toEqual(["pending-old"]);
    committer.close();
    await expect(store.purgeSession("split-generation")).resolves.toBe(true);
    await expect(store.append(message("fresh", "split-generation"))).resolves.toMatchObject({
      event: { sequence: 1 },
    });

    await expect(committer.commit(message("after-close", "split-generation"))).rejects.toThrow(
      /closed/i,
    );
    await expect(committer.retryPublish("pending-old")).rejects.toThrow(/closed/i);
    expect(() => committer.subscribe("split-generation")).toThrow(/closed/i);
  });

  it("retains the split purge blocker while an append owns a pending reservation", async () => {
    const store = new BlockingInsertStore();
    const committer = new SplitEventCommitter(store, new FlakyBus());
    const committing = committer.commit(message("blocked", "blocked"));
    await store.entered;

    expect(() => committer.close()).toThrow(/pending/i);

    store.releaseBlocked();
    await expect(committing).resolves.toMatchObject({ sequence: 1 });
    await expect(store.purgeSession("blocked")).rejects.toMatchObject({
      code: "SESSION_PURGE_UNSUPPORTED",
      component: "event_delivery",
    } satisfies Partial<SessionPurgeUnsupportedError>);

    committer.close();
    await expect(store.purgeSession("blocked")).resolves.toBe(true);
  });

  it("prevents an active split subscription from crossing a reused generation", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const oldCommitter = new SplitEventCommitter(store, bus);
    const old = await oldCommitter.commit(message("old", "split-subscription-generation"));
    const oldSubscription = oldCommitter.subscribe("split-subscription-generation");
    await expect(oldSubscription.next()).resolves.toEqual({ value: old, done: false });

    expect(() => oldCommitter.close()).toThrow(/subscription/i);
    await expect(store.purgeSession("split-subscription-generation")).rejects.toMatchObject({
      code: "SESSION_PURGE_UNSUPPORTED",
      component: "event_delivery",
    } satisfies Partial<SessionPurgeUnsupportedError>);

    await oldSubscription.return?.();
    oldCommitter.close();
    await expect(store.purgeSession("split-subscription-generation")).resolves.toBe(true);

    const freshCommitter = new SplitEventCommitter(store, bus);
    await expect(
      freshCommitter.commit(message("fresh-one", "split-subscription-generation")),
    ).resolves.toMatchObject({ sequence: 1 });
    await expect(
      freshCommitter.commit(message("fresh-two", "split-subscription-generation")),
    ).resolves.toMatchObject({ sequence: 2 });
    await expect(oldSubscription.next()).resolves.toEqual({ value: undefined, done: true });
    freshCommitter.close();
  });

  it("retains the split blocker during reentrant subscription creation", async () => {
    const store = new NonTransactionalStore();
    const bus = new ReentrantSubscribeBus();
    const committer = new SplitEventCommitter(store, bus);
    let closeError: unknown;
    bus.onSubscribe = () => {
      try {
        committer.close();
      } catch (error) {
        closeError = error;
      }
    };

    const subscription = committer.subscribe("subscription-creation");
    expect(closeError).toBeInstanceOf(Error);
    expect((closeError as Error).message).toMatch(/subscription/i);
    await expect(store.purgeSession("subscription-creation")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );

    await subscription.return?.();
    committer.close();
    await expect(store.purgeSession("subscription-creation")).resolves.toBe(false);
  });

  it("retains synchronous construction teardown until the orphaned cursor closes", async () => {
    const store = new SyncThrowTransactionStore();
    const bus = new RetryableReturnBus();
    const committer = new SplitEventCommitter(store, bus);

    expect(() => committer.subscribe("construction-cleanup")).toThrow("transaction setup failed");
    expect(bus.returnCalls).toBe(1);
    await Promise.resolve();

    expect(() => committer.close()).toThrow(/subscription/i);
    expect(bus.returnCalls).toBe(2);
    await expect(store.purgeSession("construction-cleanup")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );

    committer.close();
    await expect(store.purgeSession("construction-cleanup")).resolves.toBe(false);
  });

  it.each(MALFORMED_LIVE_CANDIDATES)(
    "rejects $name before split subscription activation",
    async (testCase) => {
      const store = new InMemoryEventStore();
      await store.append(message("malformed-live", "malformed-live"));
      const bus = new MalformedLiveBus(testCase.candidateFactory);
      const committer = new SplitEventCommitter(store, bus);
      let subscription: AsyncIterableIterator<StoredKajiEvent> | undefined;
      let subscribeError: unknown;
      try {
        subscription = committer.subscribe("malformed-live");
      } catch (error) {
        subscribeError = error;
      }
      if (subscription !== undefined) {
        await subscription.return?.().catch(() => undefined);
      }
      await Promise.resolve();
      await Promise.resolve();

      let closeError: unknown;
      try {
        committer.close();
      } catch (error) {
        closeError = error;
      }
      let purgeError: unknown;
      let purged: boolean | undefined;
      try {
        purged = await store.purgeSession("malformed-live");
      } catch (error) {
        purgeError = error;
      }

      expect({
        rejected: subscribeError instanceof TypeError,
        activeSubscriptions: bus.activeSubscriptions,
        closeBlocked: closeError instanceof Error,
        purgeBlocked: purgeError instanceof SessionPurgeUnsupportedError,
        purged,
      }).toEqual(
        testCase.recoverable
          ? {
              rejected: true,
              activeSubscriptions: 0,
              closeBlocked: false,
              purgeBlocked: false,
              purged: true,
            }
          : {
              rejected: true,
              activeSubscriptions: 1,
              closeBlocked: true,
              purgeBlocked: true,
              purged: undefined,
            },
      );
      expect((subscribeError as Error).message).toMatch(testCase.errorPattern);
    },
  );

  it("retains an unteardownable split blocker after the committer is collected", () => {
    const completed = spawnSync("bun", ["tests/split-blocker-gc-probe.ts"], {
      cwd: process.cwd(),
      encoding: "utf8",
      timeout: 30_000,
    });

    expect(completed.status, completed.stderr).toBe(0);
    expect(JSON.parse(completed.stdout)).toEqual({
      committerCollected: true,
      activeSubscriptions: 1,
      purgeBlocked: true,
      purged: null,
      blockerRemoved: true,
      storeCollected: true,
      unregisteredStoreCollected: true,
    });
  });

  it("keeps split close fail-closed while subscription return is in flight", async () => {
    const store = new NonTransactionalStore();
    const bus = new BlockingReturnBus();
    const committer = new SplitEventCommitter(store, bus);
    const subscription = committer.subscribe("subscription-close-race");
    const closing = subscription.return!();
    await bus.returnEntered.promise;

    expect(() => committer.close()).toThrow(/subscription/i);
    await expect(store.purgeSession("subscription-close-race")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );

    bus.releaseReturn();
    await closing;
    await subscription.return?.();
    expect(bus.returnCalls).toBe(1);
    committer.close();
    await expect(store.purgeSession("subscription-close-race")).resolves.toBe(false);
  });

  it("retries rejected split subscription teardown before unregistering", async () => {
    const store = new InMemoryEventStore();
    const bus = new RetryableReturnBus();
    const committer = new SplitEventCommitter(store, bus);
    await expect(
      committer.commit(message("old", "subscription-close-retry")),
    ).resolves.toMatchObject({ sequence: 1 });
    const subscription = committer.subscribe("subscription-close-retry");
    const subscriptions = (committer as unknown as { subscriptions: Set<unknown> }).subscriptions;
    const deleteSubscription = subscriptions.delete.bind(subscriptions);
    let unregisterCalls = 0;
    subscriptions.delete = (value) => {
      unregisterCalls += 1;
      return deleteSubscription(value);
    };

    const firstClose = subscription.return!();
    const joinedClose = subscription.return!();
    await expect(Promise.all([firstClose, joinedClose])).rejects.toThrow("return unavailable");
    expect(bus.returnCalls).toBe(1);
    expect(unregisterCalls).toBe(0);
    expect(() => committer.close()).toThrow(/subscription/i);
    await expect(store.purgeSession("subscription-close-retry")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );

    await expect(subscription.return?.()).resolves.toEqual({ value: undefined, done: true });
    await expect(subscription.return?.()).resolves.toEqual({ value: undefined, done: true });
    expect(bus.returnCalls).toBe(2);
    expect(unregisterCalls).toBe(1);
    committer.close();
    await expect(store.purgeSession("subscription-close-retry")).resolves.toBe(true);

    const fresh = new SplitEventCommitter(store, new EventBus());
    await expect(fresh.commit(message("fresh", "subscription-close-retry"))).resolves.toMatchObject(
      {
        sequence: 1,
      },
    );
    fresh.close();
  });

  it("preserves a live schema error when split teardown rejects and remains retryable", async () => {
    const row: Record<string, unknown> = { ...message("invalid-live"), sequence: 1 };
    delete row.version;
    const store = new InMemoryEventStore();
    const bus = new SchemaErrorRetryableReturnBus(row);
    const committer = new SplitEventCommitter(store, bus);
    const subscription = committer.subscribe("s1");

    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_SCHEMA_INCOMPATIBLE",
      path: "/version",
    } satisfies Partial<EventSchemaIncompatibleError>);
    expect(bus.returnCalls).toBe(1);
    expect(bus.activeSubscriptions).toBe(1);
    expect(() => committer.close()).toThrow(/subscription/i);
    await expect(store.purgeSession("s1")).rejects.toBeInstanceOf(SessionPurgeUnsupportedError);

    await expect(subscription.return?.()).resolves.toEqual({ value: undefined, done: true });
    expect(bus.returnCalls).toBe(2);
    expect(bus.activeSubscriptions).toBe(0);
    committer.close();
    await expect(store.purgeSession("s1")).resolves.toBe(false);
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

  it.each(["id", "version", "timestamp"])(
    "validates a stable custom-store backlog row missing %s before attachment",
    async (field) => {
      const row: Record<string, unknown> = { ...message("raw-stable"), sequence: 8 };
      delete row[field];
      const committer = new InMemoryEventCommitter(new RawBacklogStore(row));
      const subscription = committer.subscribe("s1", { afterSequence: 7 });

      await expect(subscription.next()).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${field}`,
      } satisfies Partial<EventSchemaIncompatibleError>);
      expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
      const subscribers = (committer as unknown as { subscribers: Map<string, Set<unknown>> })
        .subscribers;
      expect(subscribers.size).toBe(0);
    },
  );

  it("snapshots a custom-store append result before field validation or fanout", async () => {
    let getterCalls = 0;
    const row = storedToolResultAccessor("raw-stable-accessor", () => {
      getterCalls += 1;
    });
    const committer = new InMemoryEventCommitter(new RawAppendStore(row));
    const subscription = committer.subscribe("s1", { afterSequence: 7 });

    await expect(committer.commit(message("live-input"))).rejects.toMatchObject({
      code: "EVENT_SCHEMA_INCOMPATIBLE",
      path: "/result",
    } satisfies Partial<EventSchemaIncompatibleError>);
    expect(getterCalls).toBe(0);
    expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
    expect((subscription as unknown as { inner: { size: number } }).inner.size).toBe(0);
    await subscription.return?.();
  });

  it("snapshots a custom-store backlog row before field validation or return", async () => {
    let getterCalls = 0;
    const row = storedToolResultAccessor("raw-stable-backlog-accessor", () => {
      getterCalls += 1;
    });
    const committer = new InMemoryEventCommitter(new RawBacklogStore(row));
    const subscription = committer.subscribe("s1", { afterSequence: 7 });

    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_SCHEMA_INCOMPATIBLE",
      path: "/result",
    } satisfies Partial<EventSchemaIncompatibleError>);
    expect(getterCalls).toBe(0);
    expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
    expect(
      (committer as unknown as { subscribers: Map<string, Set<unknown>> }).subscribers.size,
    ).toBe(0);
  });

  it.each(["id", "version", "timestamp"])(
    "validates a stable custom-store live result missing %s before fanout",
    async (field) => {
      const row: Record<string, unknown> = { ...message("raw-stable-live"), sequence: 8 };
      delete row[field];
      const committer = new InMemoryEventCommitter(new RawAppendStore(row));
      const subscription = committer.subscribe("s1", { afterSequence: 7 });

      await expect(committer.commit(message("live-input"))).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${field}`,
      } satisfies Partial<EventSchemaIncompatibleError>);
      expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
      const subscribers = (committer as unknown as { subscribers: Map<string, Set<unknown>> })
        .subscribers;
      expect(subscribers.size).toBe(1);
      await subscription.return?.();
      expect(subscribers.size).toBe(0);
    },
  );

  it("snapshots a custom live row before field validation or cursor advancement", async () => {
    let getterCalls = 0;
    const row = storedToolResultAccessor("raw-split-bus-accessor", () => {
      getterCalls += 1;
    });
    const bus = new RawLiveBus(row);
    const committer = new SplitEventCommitter(new InMemoryEventStore(), bus);
    const subscription = committer.subscribe("s1", { afterSequence: 7 });

    await expect(subscription.next()).rejects.toMatchObject({
      code: "EVENT_SCHEMA_INCOMPATIBLE",
      path: "/result",
    } satisfies Partial<EventSchemaIncompatibleError>);
    expect(getterCalls).toBe(0);
    expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
    expect(bus.closedSubscriptions).toBe(1);
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

  it("reserves split capacity before a cross-session append", async () => {
    let entered!: () => void;
    let release!: () => void;
    const publishEntered = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const publishRelease = new Promise<void>((resolve) => {
      release = resolve;
    });
    const bus: EventBusProtocol<StoredKajiEvent> = {
      async publish() {
        entered();
        await publishRelease;
        throw new Error("publish failed");
      },
      subscribe() {
        return (async function* () {})();
      },
      close() {},
    };
    const store = new InMemoryEventStore();
    const committer = new SplitEventCommitter(store, bus, { maxPendingEvents: 1 });
    const first = committer.commit(message("first", "first"));
    await publishEntered;

    await expect(committer.commit(message("second", "second"))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
    expect(await store.lastSequence("second")).toBe(0);

    release();
    await expect(first).rejects.toBeInstanceOf(EventDeliveryError);
    expect(committer.pendingEventIds()).toEqual(["first"]);
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
    committer.close();
  });

  it("closes eager split delivery when the backlog read fails", async () => {
    const bus = new TrackingLiveBus();
    const committer = new SplitEventCommitter(new FailingReadStore(), bus);
    const subscription = committer.subscribe("s1");

    await expect(subscription.next()).rejects.toThrow("read failed");

    expect(bus.closedSubscriptions).toBe(1);
    committer.close();
  });

  it.each(["id", "version", "timestamp"])(
    "validates a split custom-store backlog row missing %s before delivery",
    async (field) => {
      const row: Record<string, unknown> = { ...message("raw-split"), sequence: 8 };
      delete row[field];
      const bus = new TrackingLiveBus();
      const committer = new SplitEventCommitter(new RawBacklogStore(row), bus);
      const subscription = committer.subscribe("s1", { afterSequence: 7 });

      await expect(subscription.next()).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${field}`,
      } satisfies Partial<EventSchemaIncompatibleError>);
      expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
      expect(bus.closedSubscriptions).toBe(1);
    },
  );

  it.each(["id", "version", "timestamp"])(
    "validates a split custom-store live result missing %s before publication",
    async (field) => {
      const row: Record<string, unknown> = { ...message("raw-split-live"), sequence: 8 };
      delete row[field];
      const bus = new TrackingLiveBus();
      const committer = new SplitEventCommitter(new RawAppendStore(row), bus);
      const subscription = committer.subscribe("s1", { afterSequence: 7 });

      await expect(committer.commit(message("live-input"))).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${field}`,
      } satisfies Partial<EventSchemaIncompatibleError>);
      expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
      expect(bus.published).toEqual([]);
      await subscription.return?.();
      expect(bus.closedSubscriptions).toBe(1);
    },
  );

  it.each(["id", "version", "timestamp"])(
    "validates a split live bus row missing %s before cursor advancement",
    async (field) => {
      const row: Record<string, unknown> = { ...message("raw-split-bus"), sequence: 8 };
      delete row[field];
      const bus = new RawLiveBus(row);
      const committer = new SplitEventCommitter(new InMemoryEventStore(), bus);
      const subscription = committer.subscribe("s1", { afterSequence: 7 });

      await expect(subscription.next()).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${field}`,
      } satisfies Partial<EventSchemaIncompatibleError>);
      expect((subscription as unknown as { cursor: number }).cursor).toBe(7);
      expect(bus.closedSubscriptions).toBe(1);
    },
  );

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
