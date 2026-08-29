import { describe, expect, it, vi } from "vitest";

import { AgentBuilder, AgentRuntime, KajiEvent, StoredKajiEvent, EventType } from "@irogane/kaji";
import { InMemoryEventCommitter } from "@/events/committer";
import { MockProvider } from "@/providers/mock";
import { InMemoryEventStore } from "@/events/store";

describe("runtime event committer", () => {
  it("requires an explicit committer at the direct runtime boundary", () => {
    const provider = new MockProvider({ reply: "ok" });
    const store = new InMemoryEventStore();

    expect(() => new AgentRuntime({ provider, store } as never)).toThrow(
      /requires an event committer/i,
    );
  });

  it("derives runtime reads from an injected committer store", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "ok" }))
      .build({ committer });

    await runtime.appendEvent(
      KajiEvent.parse({
        id: "custom-committer",
        type: EventType.USER_MESSAGE,
        session_id: "custom",
        content: "hello",
      }),
    );

    expect((await runtime.history("custom")).map(({ id }) => id)).toEqual(["custom-committer"]);
    expect(await store.lastSequence("custom")).toBe(1);
  });

  it("rejects mismatched explicit stores in both builder and runtime wiring", () => {
    const committerStore = new InMemoryEventStore();
    const otherStore = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(committerStore);
    const provider = new MockProvider({ reply: "ok" });

    expect(() =>
      new AgentBuilder().provider(provider).build({ committer, store: otherStore }),
    ).toThrow(/store must match the injected committer store/i);
    expect(() => new AgentRuntime({ provider, store: otherStore, committer })).toThrow(
      /store must match the injected committer store/i,
    );
    expect(() =>
      new AgentBuilder().provider(provider).build({ committer, store: committerStore }),
    ).not.toThrow();
  });

  it("uses the canonical append path and deduplicates drafts", async () => {
    const runtime = new AgentBuilder().provider(new MockProvider({ reply: "ok" })).build();
    const draft = KajiEvent.parse({
      type: EventType.USER_MESSAGE,
      session_id: "seeded",
      content: "hello",
    });

    const stored = await runtime.appendEvent(draft);
    const duplicate = await runtime.appendEvent({ ...draft });

    expect(stored.sequence).toBe(1);
    expect(duplicate).toStrictEqual(stored);
    expect(duplicate).not.toBe(stored);
    expect((await runtime.history("seeded")).map(({ sequence }) => sequence)).toEqual([1]);
  });

  it("returns only persisted events after the turn cursor", async () => {
    const runtime = new AgentBuilder().provider(new MockProvider({ reply: "ok" })).build();

    const first = await runtime.turn("first", { sessionId: "session" });
    const second = await runtime.turn("second", { sessionId: "session" });

    expect(first.events.map(({ sequence }) => sequence)).toEqual(
      Array.from({ length: first.events.length }, (_, index) => index + 1),
    );
    expect(second.events.every((event) => StoredKajiEvent.safeParse(event).success)).toBe(true);
    expect(second.events[0]?.sequence).toBe(first.events.at(-1)!.sequence + 1);
    await expect(
      runtime.history("session", { afterSequence: first.events.at(-1)!.sequence, limit: 2 }),
    ).resolves.toEqual(second.events.slice(0, 2));
  });

  it("bounds history by default while preserving explicit cursor pages", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder().provider(new MockProvider({ reply: "ok" })).build({ store });
    const getEvents = vi.spyOn(store, "getEvents");

    await runtime.history("paged");
    expect(getEvents).toHaveBeenLastCalledWith("paged", { limit: 1_024 });

    await runtime.history("paged", { afterSequence: 9, limit: 2 });
    expect(getEvents).toHaveBeenLastCalledWith("paged", { afterSequence: 9, limit: 2 });
  });
});
