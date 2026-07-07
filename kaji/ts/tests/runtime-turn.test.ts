/**
 * Tests for AgentRuntime.turn — the one-call hello-world wrapper.
 */
import { describe, it, expect } from "vitest";
import { AgentBuilder, EventBus, InMemoryEventStore, EventType } from "@kaji/sdk";
import { MockProvider } from "@/providers/mock";

function build(provider: MockProvider) {
  const store = new InMemoryEventStore();
  const runtime = new AgentBuilder().provider(provider).build({ bus: new EventBus(), store });
  return { runtime, store };
}

describe("AgentRuntime.turn", () => {
  it("returns text for a simple reply", async () => {
    const { runtime } = build(new MockProvider({ reply: "hello world" }));
    const r = await runtime.turn("ping");
    expect(r.text).toBe("hello world");
    expect(r.sessionId).toBeTruthy();
    expect(r.toolCallEvents).toEqual([]);
  });

  it("generates a fresh session id when none is given", async () => {
    const { runtime } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first");
    const r2 = await runtime.turn("second");
    expect(r1.sessionId).not.toBe(r2.sessionId);
  });

  it("reuses an existing session id", async () => {
    const { runtime, store } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first", { sessionId: "s-1" });
    const r2 = await runtime.turn("second", { sessionId: "s-1" });
    expect(r1.sessionId).toBe("s-1");
    expect(r2.sessionId).toBe("s-1");
    const events = await store.getEvents("s-1");
    expect(events.filter((e) => e.type === EventType.SESSION_CREATED)).toHaveLength(1);
  });

  it("emits TOOL_CALL_REQUESTED when the model calls a tool", async () => {
    const { runtime } = build(new MockProvider({ toolCall: { name: "ping", args: {} } }));
    const r = await runtime.turn("call ping");
    expect(r.toolCallEvents.some((e) => e.type === EventType.TOOL_CALL_REQUESTED)).toBe(true);
  });

  it("scopes events to this turn only", async () => {
    const { runtime } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first", { sessionId: "s-1" });
    const r2 = await runtime.turn("second", { sessionId: "s-1" });
    expect(r1.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(true);
    expect(r2.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(false);
  });

  it("uses defaultUuid (works without crypto.randomUUID)", async () => {
    // Simulate a restricted runtime where crypto.randomUUID is unavailable.
    // The runtime must not throw — defaultUuid falls back to a Math.random hex.
    const originalCrypto = globalThis.crypto;
    Object.defineProperty(globalThis, "crypto", {
      value: undefined,
      configurable: true,
    });
    try {
      const { runtime } = build(new MockProvider({ reply: "ok" }));
      const r = await runtime.turn("hi");
      expect(r.sessionId).toBeTruthy();
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        value: originalCrypto,
        configurable: true,
      });
    }
  });

  it("propagates provider errors", async () => {
    class FailingProvider {
      async generate() {
        throw new Error("provider boom");
      }
      // oxlint-disable-next-line require-yield -- throw is observed when the stream is consumed.
      async *generateStream(): AsyncGenerator<never> {
        throw new Error("provider boom");
      }
    }
    const { runtime } = build(new FailingProvider() as unknown as MockProvider);
    await expect(runtime.turn("hi")).rejects.toThrow("provider boom");
  });
});
