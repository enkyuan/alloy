import { describe, expect, it } from "vitest";

import * as eventErrors from "@/events/errors";
import {
  EventIdConflictError,
  EventStoreCapacityError,
  SessionPurgeBusyError,
} from "@/events/errors";
import { KajiEvent, type NewKajiEvent } from "@/events/schemas";
import { InMemoryEventStore, supportsSessionPurge, type AppendResult } from "@/events/store";
import {
  beginStoreSessionPurge,
  coordinatedSessionPurge,
  finishSessionCleanup,
  SessionPurgeAuthorization,
} from "@/events/session-lifecycle";
import { EventType } from "@/events/types";
import { NestedEventTransactionError } from "@/internal/keyed-serial";

function userMessage(
  sessionId: string,
  content: string,
  timestamp: number,
  id = `${sessionId}-${content}`,
) {
  return KajiEvent.parse({
    id,
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content,
    timestamp,
  });
}

class BarrierStore extends InMemoryEventStore {
  readonly entered: Promise<void>;
  private enter!: () => void;
  private readonly release: Promise<void>;
  private unblock!: () => void;

  constructor(private readonly blockedSession: string) {
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
    if (event.session_id === this.blockedSession) {
      this.enter();
      await this.release;
    }
    return super.insertReserved(event);
  }
}

describe("InMemoryEventStore", () => {
  it("rejects durable poison before admission and preserves sequence one", async () => {
    const store = new InMemoryEventStore();
    const poisoned = KajiEvent.parse({
      id: "poisoned",
      type: EventType.TOOL_CALL_COMPLETED,
      version: "1.0",
      timestamp: 1,
      session_id: "durable-boundary",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      result: {},
      metadata: {},
    });
    (poisoned as { result: unknown }).result = () => undefined;
    const InvalidDurableValueError = (
      eventErrors as typeof eventErrors & {
        InvalidDurableValueError?: new (...args: never[]) => Error;
      }
    ).InvalidDurableValueError;
    expect(InvalidDurableValueError).toBeTypeOf("function");
    await expect(store.append(poisoned)).rejects.toBeInstanceOf(InvalidDurableValueError!);
    expect(await store.getEvents("durable-boundary")).toEqual([]);
    expect(await store.lastSequence("durable-boundary")).toBe(0);

    let getterCalls = 0;
    const accessor: Record<string, unknown> = {
      id: "accessor",
      type: EventType.TOOL_CALL_COMPLETED,
      version: "1.0",
      timestamp: 2,
      session_id: "durable-boundary",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "accessor-call",
      metadata: {},
    };
    Object.defineProperty(accessor, "result", {
      enumerable: true,
      get() {
        getterCalls++;
        return { secret: "sk-accessor-secret" };
      },
    });
    await expect(store.append(accessor as never)).rejects.toMatchObject({
      code: "INVALID_DURABLE_VALUE",
      subject: "tool_result",
    });
    expect(getterCalls).toBe(0);
    expect(await store.getEvents("durable-boundary")).toEqual([]);

    const oversized = KajiEvent.parse({
      id: "oversized",
      type: EventType.USER_MESSAGE,
      version: "1.0",
      timestamp: 3,
      session_id: "durable-boundary",
      content: "😀".repeat(Math.floor(1_048_576 / 4) + 1),
      metadata: {},
    });
    const DurableJsonLimitError = (
      eventErrors as typeof eventErrors & {
        DurableJsonLimitError?: new (...args: never[]) => Error;
      }
    ).DurableJsonLimitError;
    expect(DurableJsonLimitError).toBeTypeOf("function");
    await expect(store.append(oversized)).rejects.toBeInstanceOf(DurableJsonLimitError!);
    expect(await store.getEvents("durable-boundary")).toEqual([]);

    const accepted = await store.append(userMessage("durable-boundary", "ok", 4, "accepted"));
    expect(accepted.event.sequence).toBe(1);
    expect((await store.getEvents("durable-boundary")).map((event) => event.id)).toEqual([
      "accepted",
    ]);
  });

  it("preserves append order when timestamps are equal or backdated", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("s1", "first", 200));
    await store.append(userMessage("s1", "second", 200));
    await store.append(userMessage("s1", "third", 100));

    const events = await store.getEvents("s1");
    expect(events.map((event) => event.sequence)).toEqual([1, 2, 3]);
    expect(
      events.map((event) => (event.type === EventType.USER_MESSAGE ? event.content : "")),
    ).toEqual(["first", "second", "third"]);
  });

  it("uses an exclusive cursor and exact limit", async () => {
    const store = new InMemoryEventStore();
    for (let index = 1; index <= 5; index++) {
      await store.append(userMessage("s1", String(index), index));
    }

    expect(
      (await store.getEvents("s1", { afterSequence: 2, limit: 2 })).map((e) => e.sequence),
    ).toEqual([3, 4]);
    expect(await store.getEvents("s1", { afterSequence: 2, limit: 0 })).toEqual([]);
    expect(await store.lastSequence("s1")).toBe(5);
    expect(await store.lastSequence("missing")).toBe(0);
  });

  it("deduplicates identical ids and rejects conflicting payloads", async () => {
    const store = new InMemoryEventStore();
    const event = userMessage("s1", "same", 1, "event-1");
    const first = await store.append(event);
    const duplicate = await store.append({ ...event });

    expect(first.inserted).toBe(true);
    expect(duplicate).toEqual({ event: first.event, inserted: false });
    await expect(store.append(userMessage("s1", "different", 1, "event-1"))).rejects.toBeInstanceOf(
      EventIdConflictError,
    );
  });

  it("purges one session from every owned index without affecting another session", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("purged", "prompt-canary", 1, "purged-user"));
    await store.append(
      KajiEvent.parse({
        id: "purged-tool-request",
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: "purged",
        turn_id: "purged-turn",
        tool_name: "lookup",
        tool_call_id: "purged-call",
        tool_args: { query: "args-canary" },
      }),
    );
    await store.append(
      KajiEvent.parse({
        id: "purged-tool-result",
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "purged",
        turn_id: "purged-turn",
        tool_name: "lookup",
        tool_call_id: "purged-call",
        result: { value: "result-canary" },
      }),
    );
    await store.append(userMessage("retained", "other-canary", 2, "retained-user"));
    const listener = () => true;
    await store.sessionTransaction("purged", async (transaction) => {
      transaction.attachListenerLocked(listener);
    });

    expect(supportsSessionPurge(store)).toBe(true);
    await expect(store.purgeSession("purged")).rejects.toBeInstanceOf(SessionPurgeBusyError);
    expect((await store.getEvents("purged")).map((event) => event.id)).toHaveLength(3);
    await store.sessionTransaction("purged", async (transaction) => {
      transaction.detachListenerLocked(listener);
    });
    await expect(store.purgeSession("purged")).resolves.toBe(true);
    expect(await store.getEvents("purged")).toEqual([]);
    expect((await store.getEvents("retained")).map((event) => event.id)).toEqual(["retained-user"]);
    expect(store.activeListenerCount).toBe(0);
    expect(store.activeSessionLaneCount).toBe(0);

    await expect(
      store.append(userMessage("fresh", "replacement", 3, "purged-user")),
    ).resolves.toMatchObject({ inserted: true, event: { sequence: 1 } });
    await expect(store.purgeSession("purged")).resolves.toBe(false);
  });

  it("rejects invalid purge session ids before mutating the store", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("retained", "safe", 1, "retained"));

    await expect(store.purgeSession("")).rejects.toThrow();
    await expect(store.purgeSession("   ")).rejects.toThrow();
    await expect(store.purgeSession(null as never)).rejects.toThrow();
    expect((await store.getEvents("retained")).map((event) => event.id)).toEqual(["retained"]);
  });

  it("scopes internal purge authorization to one store, session, lease, and delete", async () => {
    const store = new InMemoryEventStore();
    const other = new InMemoryEventStore();
    await store.append(userMessage("authorized", "old", 1));
    const lease = beginStoreSessionPurge(store, "authorized");
    try {
      await expect(
        store[coordinatedSessionPurge]("other-session", lease.authorization),
      ).rejects.toBeInstanceOf(SessionPurgeBusyError);
      await expect(
        other[coordinatedSessionPurge]("authorized", lease.authorization),
      ).rejects.toBeInstanceOf(SessionPurgeBusyError);
      await expect(
        store[coordinatedSessionPurge]("authorized", new SessionPurgeAuthorization()),
      ).rejects.toBeInstanceOf(SessionPurgeBusyError);

      await expect(store[coordinatedSessionPurge]("authorized", lease.authorization)).resolves.toBe(
        true,
      );
      await expect(
        store[coordinatedSessionPurge]("authorized", lease.authorization),
      ).rejects.toBeInstanceOf(SessionPurgeBusyError);
      finishSessionCleanup(lease);
    } finally {
      lease.release();
    }
    expect(await store.getEvents("authorized")).toEqual([]);
  });

  it("rejects purge during an in-flight append without deleting the generation", async () => {
    const store = new BarrierStore("raced");
    const append = store.append(userMessage("raced", "one", 1, "raced-event"));
    await store.entered;

    await expect(store.purgeSession("raced")).rejects.toBeInstanceOf(SessionPurgeBusyError);

    store.releaseBlocked();
    await expect(append).resolves.toMatchObject({ inserted: true });
    expect(await store.getEvents("raced")).toHaveLength(1);
    await expect(store.purgeSession("raced")).resolves.toBe(true);
    expect(await store.getEvents("raced")).toEqual([]);
    expect(store.activeSessionLaneCount).toBe(0);
    expect(store.activeIdReservationCount).toBe(0);
  });

  it("lets an unrelated session commit while another store lane is blocked", async () => {
    const store = new BarrierStore("blocked");
    const blocked = store.append(userMessage("blocked", "one", 1, "blocked"));
    await store.entered;

    await expect(store.append(userMessage("free", "one", 1, "free"))).resolves.toMatchObject({
      event: { sequence: 1 },
    });

    store.releaseBlocked();
    await expect(blocked).resolves.toMatchObject({ event: { sequence: 1 } });
    expect(store.activeSessionLaneCount).toBe(0);
  });

  it("keeps same-session commits FIFO and releases lane state", async () => {
    const store = new BarrierStore("same");
    const first = store.append(userMessage("same", "one", 1, "first"));
    await store.entered;
    const second = store.append(userMessage("same", "two", 2, "second"));
    let secondSettled = false;
    void second.finally(() => {
      secondSettled = true;
    });
    await Promise.resolve();
    expect(secondSettled).toBe(false);

    store.releaseBlocked();
    await expect(first).resolves.toMatchObject({ event: { sequence: 1 } });
    await expect(second).resolves.toMatchObject({ event: { sequence: 2 } });
    expect(store.activeSessionLaneCount).toBe(0);
    expect(store.activeIdReservationCount).toBe(0);
  });

  it("rejects nested store transactions instead of deadlocking", async () => {
    const store = new InMemoryEventStore();
    await expect(
      store.sessionTransaction("s1", () => store.sessionTransaction("s1", async () => undefined)),
    ).rejects.toBeInstanceOf(NestedEventTransactionError);
    expect(store.activeSessionLaneCount).toBe(0);
  });

  it("rejects a child transaction while its inherited parent marker is active", async () => {
    const store = new InMemoryEventStore();
    await store.sessionTransaction("parent", async () => {
      const child = Promise.resolve().then(() =>
        store.append(userMessage("child", "one", 1, "child")),
      );
      await expect(child).rejects.toBeInstanceOf(NestedEventTransactionError);
    });
    expect(store.activeSessionLaneCount).toBe(0);
  });

  it("allows a child created during a hold to commit after release", async () => {
    const store = new InMemoryEventStore();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let child!: Promise<AppendResult>;

    await store.sessionTransaction("parent", async () => {
      child = gate.then(() => store.append(userMessage("delayed", "one", 1, "delayed")));
    });
    release();

    await expect(child).resolves.toMatchObject({ inserted: true });
    expect(store.activeSessionLaneCount).toBe(0);
  });

  it("does not admit a new session while a retained session lane is active", async () => {
    const store = new InMemoryEventStore({ maxSessions: 1 });
    await store.append(
      KajiEvent.parse({ id: "closed", type: EventType.SESSION_CLOSED, session_id: "closed" }),
    );
    let entered!: () => void;
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const holder = store.sessionTransaction("closed", async () => {
      entered();
      await held;
    });
    await started;

    await expect(store.append(userMessage("new", "one", 1, "new"))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
    release();
    await holder;
    await expect(store.append(userMessage("new", "one", 1, "new"))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
  });

  it("rejects a cross-session id conflict while the owner is blocked", async () => {
    const store = new BarrierStore("owner");
    const owner = store.append(userMessage("owner", "one", 1, "shared"));
    await store.entered;

    await expect(
      store.append(userMessage("other", "different", 1, "shared")),
    ).rejects.toBeInstanceOf(EventIdConflictError);
    store.releaseBlocked();
    await expect(owner).resolves.toMatchObject({ inserted: true });
    expect(store.activeIdReservationCount).toBe(0);
  });

  it("deep-clones and freezes stored event payloads", async () => {
    const store = new InMemoryEventStore();
    const draft = KajiEvent.parse({
      id: "immutable",
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "s1",
      turn_id: "turn-1",
      metadata: { audit: { level: 1 } },
      tool_name: "search",
      tool_call_id: "call-1",
      tool_args: { filters: [{ active: true }] },
    });
    const { event: stored } = await store.append(draft);
    if (
      draft.type !== EventType.TOOL_CALL_REQUESTED ||
      stored.type !== EventType.TOOL_CALL_REQUESTED
    ) {
      throw new Error("expected tool-call events");
    }

    (draft.metadata.audit as { level: number }).level = 9;
    (draft.tool_args.filters as Array<{ active: boolean }>)[0]!.active = false;

    expect(Object.isFrozen(stored)).toBe(true);
    expect(Object.isFrozen(stored.metadata)).toBe(true);
    expect(Object.isFrozen(stored.tool_args.filters)).toBe(true);
    expect(Object.isFrozen((stored.tool_args.filters as readonly object[])[0])).toBe(true);
    expect((stored.metadata.audit as { readonly level: number }).level).toBe(1);
    expect((stored.tool_args.filters as readonly { readonly active: boolean }[])[0]?.active).toBe(
      true,
    );
    expect(() => {
      (stored.metadata.audit as { level: number }).level = 2;
    }).toThrow(TypeError);

    const [persisted] = await store.getEvents("s1");
    expect((persisted!.metadata.audit as { readonly level: number }).level).toBe(1);
  });

  it("enforces per-session and active-session bounds", async () => {
    const perSession = new InMemoryEventStore({ maxEventsPerSession: 1 });
    await perSession.append(userMessage("s1", "one", 1));
    await expect(perSession.append(userMessage("s1", "two", 2))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );

    const activeSessions = new InMemoryEventStore({ maxSessions: 1 });
    await activeSessions.append(userMessage("active", "one", 1));
    await expect(activeSessions.append(userMessage("other", "two", 2))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
  });

  it("requires explicit purge before reusing retained session capacity", async () => {
    const store = new InMemoryEventStore({ maxSessions: 1 });
    await store.append(userMessage("old", "one", 1));
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CLOSED, session_id: "old" }));
    await store.getEvents("old");

    await expect(store.append(userMessage("new", "two", 2))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
    expect((await store.getEvents("old")).map((event) => event.sequence)).toEqual([1, 2]);
    await expect(store.append(userMessage("new", "two", 2))).rejects.toBeInstanceOf(
      EventStoreCapacityError,
    );
  });
});
