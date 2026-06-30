import { describe, expect, it } from "vitest";

import { KajiEvent, EventBus, EventType } from "@/index";

function userMessage(sessionId: string, content: string) {
  return KajiEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content,
  });
}

describe("EventBus", () => {
  it("delivers published events to a subscriber of the same session", async () => {
    const bus = new EventBus();
    const sub = bus.subscribe("s1");

    await bus.publish(userMessage("s1", "hello"));

    const { value, done } = await sub.next();
    expect(done).toBe(false);
    expect(value?.type).toBe(EventType.USER_MESSAGE);

    await sub.return?.();
  });

  it("buffers events published before next() is awaited", async () => {
    const bus = new EventBus();
    const sub = bus.subscribe("s1");

    await bus.publish(userMessage("s1", "one"));
    await bus.publish(userMessage("s1", "two"));

    const first = await sub.next();
    const second = await sub.next();
    expect(
      [first, second].map((r) => (r.value?.type === EventType.USER_MESSAGE ? r.value.content : "")),
    ).toEqual(["one", "two"]);

    await sub.return?.();
  });

  it("does not deliver events from other sessions", async () => {
    const bus = new EventBus();
    const sub = bus.subscribe("s1");

    await bus.publish(userMessage("s2", "other"));
    await bus.publish(userMessage("s1", "mine"));

    const { value } = await sub.next();
    expect(value?.type === EventType.USER_MESSAGE ? value.content : "").toBe("mine");

    await sub.return?.();
  });

  it("fans out to multiple subscribers", async () => {
    const bus = new EventBus();
    const a = bus.subscribe("s1");
    const b = bus.subscribe("s1");

    await bus.publish(userMessage("s1", "broadcast"));

    const [ra, rb] = await Promise.all([a.next(), b.next()]);
    expect(ra.value?.type).toBe(EventType.USER_MESSAGE);
    expect(rb.value?.type).toBe(EventType.USER_MESSAGE);

    bus.close();
  });

  it("completes the iterator when closed", async () => {
    const bus = new EventBus();
    const sub = bus.subscribe("s1");
    const pending = sub.next();
    bus.close();
    expect((await pending).done).toBe(true);
  });
});
