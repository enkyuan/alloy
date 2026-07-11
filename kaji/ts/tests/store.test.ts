import { describe, expect, it } from "vitest";

import { EventIdConflictError, EventStoreCapacityError } from "@/events/errors";
import { KajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";

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

describe("InMemoryEventStore", () => {
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
    expect((persisted?.metadata.audit as { readonly level: number }).level).toBe(1);
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

  it("evicts only the least-recently-used closed session", async () => {
    const store = new InMemoryEventStore({ maxSessions: 2 });
    await store.append(
      KajiEvent.parse({ id: "closed-a", type: EventType.SESSION_CLOSED, session_id: "a" }),
    );
    await store.append(
      KajiEvent.parse({ id: "closed-b", type: EventType.SESSION_CLOSED, session_id: "b" }),
    );
    await store.getEvents("b");
    await store.append(userMessage("c", "new", 1));

    expect(await store.getEvents("a")).toEqual([]);
    expect(await store.getEvents("b")).toHaveLength(1);
    expect(await store.getEvents("c")).toHaveLength(1);
  });
});
