/**
 * Tests for AgentRuntime.turn — the one-call hello-world wrapper.
 */
import { describe, it, expect } from "vitest";
import {
  AgentBuilder,
  InMemoryEventStore,
  InMemoryToolIdempotencyLedger,
  EventType,
  KajiEvent,
  SessionPurgeUnsupportedError,
  supportsSessionPurge,
  type EventStore,
  type ModelProvider,
  type ModelResponseChunk,
  type ProviderMessage,
  type ToolIdempotencyLedger,
} from "@kaji/sdk";
import { MockProvider } from "@/providers/mock";

class NonPurgeableStore implements EventStore {
  private readonly inner = new InMemoryEventStore();
  readonly maxSessions = this.inner.maxSessions;

  append(...args: Parameters<EventStore["append"]>) {
    return this.inner.append(...args);
  }

  getEvents(...args: Parameters<EventStore["getEvents"]>) {
    return this.inner.getEvents(...args);
  }

  lastSequence(...args: Parameters<EventStore["lastSequence"]>) {
    return this.inner.lastSequence(...args);
  }
}

class ControlledPurgeStore extends InMemoryEventStore {
  readonly purgeEntered = Promise.withResolvers<void>();
  private readonly purgeRelease = Promise.withResolvers<void>();

  releasePurge(): void {
    this.purgeRelease.resolve();
  }

  override async purgeSession(sessionId: string): Promise<boolean> {
    this.purgeEntered.resolve();
    await this.purgeRelease.promise;
    return super.purgeSession(sessionId);
  }
}

class PurgeCanaryProvider implements ModelProvider {
  async generate() {
    return { content: "", toolCalls: [] };
  }

  async *generateStream(messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
    if (!messages.some((message) => message.role === "tool")) {
      yield {
        delta: "",
        toolCalls: [
          { id: "purge-canary-call", name: "purge_canary", args: { value: "args-canary" } },
        ],
      };
      return;
    }
    yield { delta: "assistant-", toolCalls: [] };
    yield { delta: "canary", toolCalls: [] };
  }
}

class RecordingProvider implements ModelProvider {
  readonly messages: ProviderMessage[][] = [];

  async generate() {
    return { content: "fresh-answer", toolCalls: [] };
  }

  async *generateStream(messages: ProviderMessage[]): AsyncGenerator<ModelResponseChunk> {
    this.messages.push(structuredClone(messages));
    yield { delta: "fresh-answer", toolCalls: [] };
  }
}

function build(provider: MockProvider) {
  const store = new InMemoryEventStore();
  const runtime = new AgentBuilder().provider(provider).build({ store });
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
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ toolCall: { name: "ping", args: {} } }))
      .integration({
        register(registry) {
          registry.register(
            { name: "ping", description: "ping", parameters: {}, risk: "read" },
            async () => ({ pong: true }),
          );
        },
      })
      .build({ store });
    const r = await runtime.turn("call ping", { context: { principalId: "test" } });
    expect(r.toolCallEvents.some((e) => e.type === EventType.TOOL_CALL_REQUESTED)).toBe(true);
  });

  it("skips tool execution when allowToolCalls is false", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration({
        register(registry) {
          registry.register(
            { name: "ping", description: "ping", parameters: {}, risk: "read" },
            async () => ({ pong: true }),
          );
        },
      })
      .strategy({ allowToolCalls: false })
      .build({ store });
    const r = await runtime.turn("call ping");
    expect(r.text).toBeTruthy();
    expect(r.toolCallEvents).toEqual([]);
    const events = await store.getEvents(r.sessionId);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_REQUESTED)).toBe(false);
  });

  it("scopes events to this turn only", async () => {
    const { runtime } = build(new MockProvider({ reply: "ok" }));
    const r1 = await runtime.turn("first", { sessionId: "s-1" });
    const r2 = await runtime.turn("second", { sessionId: "s-1" });
    expect(r1.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(true);
    expect(r2.events.some((e) => e.type === EventType.SESSION_CREATED)).toBe(false);
  });

  it("purges persisted and runtime-owned session state without disturbing shared-store peers", async () => {
    const store = new InMemoryEventStore({ maxSessions: 4, maxEventsPerSession: 100 });
    let executions = 0;
    const runtime = new AgentBuilder()
      .provider(new PurgeCanaryProvider())
      .integration({
        register(registry) {
          registry.register(
            { name: "purge_canary", description: "purge canary", parameters: {}, risk: "read" },
            async () => ({ value: `result-canary-${++executions}` }),
          );
        },
      })
      .defaultContext({ principalId: "purge-test" })
      .contextWindow({ maxTurns: 1, maxCharacters: 10_000 })
      .build({ store });
    const siblingProvider = new RecordingProvider();
    const sibling = new AgentBuilder().provider(siblingProvider).build({ store });

    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "purged-session" }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: "purged-session",
        content: "old-prompt",
      }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.AGENT_MESSAGE_COMPLETED,
        session_id: "purged-session",
        content: "old-answer",
      }),
    );

    await runtime.turn("prompt-canary", { sessionId: "purged-session" });
    await sibling.turn("sibling-warm-canary", { sessionId: "purged-session" });
    await sibling.turn("keep this", { sessionId: "retained-session" });
    const retainedBefore = await sibling.history("retained-session");
    const before = JSON.stringify(await runtime.history("purged-session"));
    for (const canary of ["prompt-canary", "args-canary", "result-canary-1", "assistant-canary"]) {
      expect(before).toContain(canary);
    }
    expect(runtime.contextDiagnostics("purged-session")).toMatchObject({ droppedTurns: 1 });
    expect(runtime.streamDiagnostics("purged-session")).toMatchObject({ inputFragments: 2 });
    expect(runtime.contextIndexStats("purged-session")).toBeDefined();
    expect(sibling.contextIndexStats("purged-session")).toBeDefined();

    await expect(runtime.purgeSession("purged-session")).resolves.toBe(true);
    expect(await runtime.history("purged-session")).toEqual([]);
    expect(runtime.contextDiagnostics("purged-session")).toBeUndefined();
    expect(runtime.streamDiagnostics("purged-session")).toBeUndefined();
    expect(runtime.contextIndexStats("purged-session")).toBeUndefined();
    expect(sibling.contextDiagnostics("purged-session")).toBeUndefined();
    expect(sibling.streamDiagnostics("purged-session")).toBeUndefined();
    expect(sibling.contextIndexStats("purged-session")).toBeUndefined();
    expect(await sibling.history("retained-session")).toEqual(retainedBefore);
    expect(sibling.contextIndexStats("retained-session")).toBeDefined();

    const caches = runtime as unknown as {
      projectors: Map<string, unknown>;
      projectionTails: Map<string, unknown>;
      activeProjectionSessions: Map<string, unknown>;
      turnEventCollectors: Map<string, unknown>;
      contextDiagnosticsBySession: Map<string, unknown>;
      streamDiagnosticsBySession: Map<string, unknown>;
      providerQuarantine: Map<string, unknown>;
    };
    expect(caches.projectors.has("purged-session")).toBe(false);
    expect(caches.projectionTails.has("purged-session")).toBe(false);
    expect(caches.activeProjectionSessions.has("purged-session")).toBe(false);
    expect(caches.turnEventCollectors.size).toBe(0);
    expect(caches.contextDiagnosticsBySession.has("purged-session")).toBe(false);
    expect(caches.streamDiagnosticsBySession.has("purged-session")).toBe(false);
    expect(caches.providerQuarantine.has("purged-session")).toBe(false);

    siblingProvider.messages.length = 0;
    const fresh = await sibling.turn("fresh-prompt", { sessionId: "purged-session" });
    expect(fresh.events[0]).toMatchObject({ type: EventType.SESSION_CREATED, sequence: 1 });
    const freshProviderInput = JSON.stringify(siblingProvider.messages);
    for (const canary of [
      "old-prompt",
      "old-answer",
      "prompt-canary",
      "args-canary",
      "result-canary-1",
      "assistant-canary",
      "sibling-warm-canary",
    ]) {
      expect(freshProviderInput).not.toContain(canary);
    }
    expect(executions).toBe(1);
  });

  it("rejects unsupported stores without partially clearing runtime caches", async () => {
    const store = new NonPurgeableStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "kept" }))
      .build({ store });
    await runtime.turn("keep", { sessionId: "unsupported" });
    const history = await runtime.history("unsupported");
    const stats = runtime.contextIndexStats("unsupported");
    const diagnostics = runtime.contextDiagnostics("unsupported");

    expect(supportsSessionPurge(store)).toBe(false);
    await expect(runtime.purgeSession("")).rejects.toThrow(TypeError);
    await expect(runtime.purgeSession("unsupported")).rejects.toBeInstanceOf(
      SessionPurgeUnsupportedError,
    );
    expect(await runtime.history("unsupported")).toEqual(history);
    expect(runtime.contextIndexStats("unsupported")).toEqual(stats);
    expect(runtime.contextDiagnostics("unsupported")).toEqual(diagnostics);
  });

  it("rejects a legacy custom ledger before deleting store or cache state", async () => {
    const backing = new InMemoryToolIdempotencyLedger();
    const legacyLedger: ToolIdempotencyLedger = {
      claim: (...args) => backing.claim(...args),
      complete: (...args) => backing.complete(...args),
      retryableFailure: (...args) => backing.retryableFailure(...args),
      unknownOutcome: (...args) => backing.unknownOutcome(...args),
      releaseCompleted: (...args) => backing.releaseCompleted(...args),
    };
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "kept" }))
      .toolIdempotencyLedger(legacyLedger)
      .build({ store });
    await runtime.turn("keep", { sessionId: "legacy-ledger" });
    const history = await runtime.history("legacy-ledger");
    const stats = runtime.contextIndexStats("legacy-ledger");

    await expect(runtime.purgeSession("legacy-ledger")).rejects.toMatchObject({
      code: "SESSION_PURGE_UNSUPPORTED",
      sessionId: "legacy-ledger",
      component: "tool_idempotency_ledger",
    });
    expect(await runtime.history("legacy-ledger")).toEqual(history);
    expect(runtime.contextIndexStats("legacy-ledger")).toEqual(stats);
  });

  it("rejects attaching a new runtime while a shared-store purge is fenced", async () => {
    const store = new ControlledPurgeStore();
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "old" }))
      .build({ store });
    await runtime.turn("old", { sessionId: "registration-race" });

    const purge = runtime.purgeSession("registration-race");
    await store.purgeEntered.promise;
    expect(() =>
      new AgentBuilder().provider(new MockProvider({ reply: "new" })).build({ store }),
    ).toThrowError(
      expect.objectContaining({
        code: "SESSION_PURGE_BUSY",
        sessionId: "registration-race",
      }),
    );

    store.releasePurge();
    await expect(purge).resolves.toBe(true);
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
