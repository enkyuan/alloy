import { describe, expect, it } from "vitest";

import { AgentKitEvent, EventType, InMemoryEventStore } from "../src/index";

function userMessage(sessionId: string, content: string, timestamp: number) {
  return AgentKitEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content,
    timestamp,
  });
}

describe("InMemoryEventStore", () => {
  it("returns events ordered by timestamp regardless of append order", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("s1", "second", 200));
    await store.append(userMessage("s1", "first", 100));

    const events = await store.getEvents("s1");
    expect(events.map((e) => (e.type === EventType.USER_MESSAGE ? e.content : "")))
      .toEqual(["first", "second"]);
  });

  it("scopes events per session", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("s1", "a", 1));
    await store.append(userMessage("s2", "b", 1));

    expect(await store.getEvents("s1")).toHaveLength(1);
    expect(await store.getEvents("s2")).toHaveLength(1);
    expect(await store.getEvents("missing")).toEqual([]);
  });

  it("returns a copy, so mutations do not leak into the store", async () => {
    const store = new InMemoryEventStore();
    await store.append(userMessage("s1", "a", 1));

    const events = await store.getEvents("s1");
    events.pop();
    expect(await store.getEvents("s1")).toHaveLength(1);
  });
});
