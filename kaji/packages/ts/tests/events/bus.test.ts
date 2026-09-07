import { describe, expect, it } from "vitest";

import { KajiEvent, StoredKajiEvent, EventBus, EventType } from "@/index";
import type { StoredKajiEvent as StoredKajiEventType } from "@/events/schemas";

function userMessage(sessionId: string, content: string) {
  return KajiEvent.parse({
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content,
  });
}

function bufferedEvents(subscription: AsyncIterableIterator<unknown>): readonly unknown[] {
  return (subscription as unknown as { readonly buffer: readonly unknown[] }).buffer;
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

  it("does not retain a duplicate history backlog", async () => {
    const bus = new EventBus();

    await bus.publish(userMessage("s1", "one"));
    await bus.publish(userMessage("s1", "two"));
    const sub = bus.subscribe("s1");
    await bus.publish(userMessage("s1", "three"));

    const next = await sub.next();
    expect(next.value?.type === EventType.USER_MESSAGE ? next.value.content : "").toBe("three");

    await sub.return?.();
  });

  it("honors a stored-event afterSequence cursor", async () => {
    const bus = new EventBus<StoredKajiEventType>();
    const sub = bus.subscribe("s1", { afterSequence: 2 });

    await bus.publish(StoredKajiEvent.parse({ ...userMessage("s1", "old"), sequence: 2 }));
    await bus.publish(StoredKajiEvent.parse({ ...userMessage("s1", "new"), sequence: 3 }));

    expect((await sub.next()).value?.sequence).toBe(3);
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

  it("releases buffered event references when a subscriber closes", async () => {
    const bus = new EventBus(4);
    const sub = bus.subscribe("s1");
    await bus.publish(userMessage("s1", "one"));
    await bus.publish(userMessage("s1", "two"));
    await bus.publish(userMessage("s1", "three"));
    await sub.next();
    await sub.next();
    await bus.publish(userMessage("s1", "four"));
    await bus.publish(userMessage("s1", "five"));

    expect(bufferedEvents(sub).filter(Boolean)).toHaveLength(3);
    await sub.return?.();

    expect(bufferedEvents(sub).filter(Boolean)).toHaveLength(0);
  });

  it("releases buffered event references when a subscriber overflows", async () => {
    const bus = new EventBus(3);
    const sub = bus.subscribe("s1");
    await bus.publish(userMessage("s1", "one"));
    await bus.publish(userMessage("s1", "two"));
    await sub.next();
    await bus.publish(userMessage("s1", "three"));
    await bus.publish(userMessage("s1", "four"));
    await bus.publish(userMessage("s1", "overflow"));

    await expect(sub.next()).rejects.toMatchObject({ code: "EVENT_BUFFER_OVERFLOW" });
    expect(bufferedEvents(sub).filter(Boolean)).toHaveLength(0);
    await expect(sub.next()).resolves.toEqual({ value: undefined, done: true });
  });
});
