import { describe, expect, it } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import { KajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import {
  safeRequest,
  type AddressResolver,
  type BoundNetworkTransport,
} from "@/integrations/safe-fetch";
import type { Clock, IdFactory } from "@/internal/uuid";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "@/providers/base";
import {
  buildContext,
  ContextWindowOverflowError,
  DEFAULT_CONTEXT_WINDOW,
  type ToolExecutionContext,
} from "@/runtime/context";
import { AgentRuntime } from "@/runtime/runtime";
import { InMemorySessionTurnCoordinator } from "@/runtime/session-turn-coordinator";
import { SessionProjector } from "@/sessions/projector";
import type { Message } from "@/sessions/replay";
import { ToolExecutionController } from "@/tools/execution";
import { InMemoryToolIdempotencyLedger } from "@/tools/idempotency";
import type { ToolSpec } from "@/tools/registry";

class Deferred<T = void> {
  readonly promise: Promise<T>;
  private settle!: (value: T | PromiseLike<T>) => void;

  constructor() {
    this.promise = new Promise((resolve) => {
      this.settle = resolve;
    });
  }

  resolve(value: T extends void ? never : T): void;
  resolve(): void;
  resolve(value?: T): void {
    this.settle(value as T);
  }
}

const TEST_CLOCK: Clock = Object.freeze({
  nowWallSeconds: () => 1,
  nowMonotonic: () => 0,
});

function sequentialIds(prefix: string): IdFactory {
  let index = 0;
  return { next: (scope) => `${prefix}-${scope}-${++index}` };
}

class CountingStore extends InMemoryEventStore {
  readonly reads: Array<{
    readonly sessionId: string;
    readonly afterSequence: number;
    readonly limit: number | undefined;
  }> = [];

  override async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ) {
    this.reads.push({
      sessionId,
      afterSequence: options.afterSequence ?? 0,
      limit: options.limit,
    });
    return super.getEvents(sessionId, options);
  }
}

class BarrierProvider implements ModelProvider {
  private readonly entered: Deferred[];
  private readonly releases: Deferred[];
  private started = 0;
  active = 0;
  peak = 0;

  constructor(expectedCalls: number) {
    this.entered = Array.from({ length: expectedCalls }, () => new Deferred());
    this.releases = Array.from({ length: expectedCalls }, () => new Deferred());
  }

  waitUntilEntered(index: number): Promise<void> {
    return this.entered[index]!.promise;
  }

  release(index: number): void {
    this.releases[index]!.resolve();
  }

  async generate(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    throw new Error("BarrierProvider only supports streaming");
  }

  async *generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    const index = this.started++;
    const entered = this.entered[index];
    const release = this.releases[index];
    if (entered === undefined || release === undefined) {
      throw new Error(`Unexpected provider call ${index + 1}`);
    }
    this.active++;
    this.peak = Math.max(this.peak, this.active);
    entered.resolve();
    try {
      await release.promise;
      yield { delta: "ok", toolCalls: [] };
    } finally {
      this.active--;
    }
  }
}

function runtimeWith(
  provider: ModelProvider,
  coordinator = new InMemorySessionTurnCoordinator(),
): { runtime: AgentRuntime; coordinator: InMemorySessionTurnCoordinator } {
  const store = new InMemoryEventStore();
  return {
    coordinator,
    runtime: new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      turnCoordinator: coordinator,
      tools: [],
      idFactory: sequentialIds("runtime"),
      clock: TEST_CLOCK,
    }),
  };
}

function toolContext(sessionId: string, callId: string): ToolExecutionContext {
  return {
    principalId: "complexity",
    sessionId,
    turnId: "turn",
    requestId: "request",
    traceId: "trace",
    toolCallId: callId,
    idempotencyKey: `${sessionId}:${callId}`,
    signal: new AbortController().signal,
    metadata: {},
  };
}

async function measureToolPeak(count: number, exclusive: boolean): Promise<number> {
  const controller = new ToolExecutionController({
    limits: { maxParallel: 4, timeoutMs: null },
  });
  const gate = new Deferred();
  const initialPeak = exclusive ? 1 : 4;
  const initialStarted = new Deferred();
  let active = 0;
  let peak = 0;
  let started = 0;
  const outcomes = Array.from({ length: count }, (_, index) =>
    controller.execute({
      name: "bounded",
      args: { index },
      context: toolContext("tool-batch", `call-${index}`),
      exclusive,
      onStarted: async () => {},
      execute: async () => {
        active++;
        peak = Math.max(peak, active);
        started++;
        if (started === initialPeak) initialStarted.resolve();
        try {
          await gate.promise;
          return { index };
        } finally {
          active--;
        }
      },
    }),
  );

  await initialStarted.promise;
  expect(active).toBe(initialPeak);
  gate.resolve();
  expect((await Promise.all(outcomes)).every(({ status }) => status === "completed")).toBe(true);
  expect(await controller.drain(0)).toEqual([]);
  return peak;
}

describe("deterministic runtime complexity gates", () => {
  it.each([1, 5, 10])(
    "performs one initial suffix read for a %i-iteration tool turn",
    async (iterations) => {
      const sessionId = `iterations-${iterations}`;
      const store = new CountingStore();
      let providerCalls = 0;
      const provider: ModelProvider = {
        async generate() {
          return { content: "", toolCalls: [] };
        },
        async *generateStream() {
          providerCalls++;
          yield {
            delta: "",
            toolCalls: [{ id: `call-${providerCalls}`, name: "noop", args: {} }],
          };
        },
      };
      const tool: ToolSpec = {
        name: "noop",
        description: "deterministic no-op",
        parameters: { type: "object", additionalProperties: false },
        risk: "read",
        parallel_safe: true,
      };
      const runtime = new AgentRuntime({
        provider,
        store,
        committer: new InMemoryEventCommitter(store),
        tools: [tool],
        toolExecutor: async () => ({ ok: true }),
        defaultContext: { principalId: "complexity" },
        strategy: { maxToolIterations: iterations },
        idFactory: sequentialIds(sessionId),
        clock: TEST_CLOCK,
      });
      await store.append(
        KajiEvent.parse({
          id: `${sessionId}-created`,
          timestamp: 1,
          type: EventType.SESSION_CREATED,
          session_id: sessionId,
        }),
      );
      await store.append(
        KajiEvent.parse({
          id: `${sessionId}-user`,
          timestamp: 1,
          type: EventType.USER_MESSAGE,
          session_id: sessionId,
          content: "go",
        }),
      );
      store.reads.length = 0;

      await runtime.runTurn(sessionId);

      expect(providerCalls).toBe(iterations);
      expect(store.reads).toEqual([{ sessionId, afterSequence: 0, limit: undefined }]);
    },
  );

  it("applies each newly inserted event exactly once across repeated projector syncs", async () => {
    const sessionId = "projection";
    const store = new InMemoryEventStore();
    const append = (id: string, type: EventType, content?: string) =>
      store.append(
        KajiEvent.parse({
          id,
          timestamp: 1,
          type,
          session_id: sessionId,
          ...(content === undefined ? {} : { content }),
        }),
      );
    await append("projection-created", EventType.SESSION_CREATED);
    await append("projection-user-1", EventType.USER_MESSAGE, "one");
    await append("projection-agent-1", EventType.AGENT_MESSAGE_COMPLETED, "answer-one");
    const projector = new SessionProjector(sessionId);

    expect(await projector.sync(store)).toBe(3);
    expect(projector.appliedEvents).toBe(3);
    expect(await projector.sync(store)).toBe(0);
    expect(projector.appliedEvents).toBe(3);

    await append("projection-user-2", EventType.USER_MESSAGE, "two");
    await append("projection-agent-2", EventType.AGENT_MESSAGE_COMPLETED, "answer-two");
    expect(await projector.sync(store)).toBe(2);
    expect(projector.appliedEvents).toBe(5);
    expect(projector.lastSequence).toBe(5);
  });

  it("serializes 25 same-session provider calls and permits cross-session overlap", async () => {
    const sameProvider = new BarrierProvider(25);
    const same = runtimeWith(sameProvider);
    const turns = Array.from({ length: 25 }, (_, index) =>
      same.runtime.turn(`same-${index}`, { sessionId: "same" }),
    );
    for (let index = 0; index < turns.length; index++) {
      await sameProvider.waitUntilEntered(index);
      expect(sameProvider.active).toBe(1);
      sameProvider.release(index);
    }
    await Promise.all(turns);
    expect(sameProvider.peak).toBe(1);
    expect(same.coordinator.entryCount).toBe(0);
    expect(same.coordinator.waitingCount).toBe(0);

    const crossProvider = new BarrierProvider(2);
    const cross = runtimeWith(crossProvider);
    const first = cross.runtime.turn("first", { sessionId: "cross-a" });
    const second = cross.runtime.turn("second", { sessionId: "cross-b" });
    await Promise.all([crossProvider.waitUntilEntered(0), crossProvider.waitUntilEntered(1)]);
    expect(crossProvider.active).toBe(2);
    crossProvider.release(0);
    crossProvider.release(1);
    await Promise.all([first, second]);
    expect(crossProvider.peak).toBe(2);
    expect(cross.coordinator.entryCount).toBe(0);
    expect(cross.coordinator.waitingCount).toBe(0);
  });

  it("caps 100 parallel-safe handlers at four and default handlers at one", async () => {
    expect(await measureToolPeak(100, false)).toBe(4);
    expect(await measureToolPeak(10, true)).toBe(1);
  });

  it("keeps the idempotency ledger at its configured completed-entry bound", async () => {
    let now = 0;
    const ledger = new InMemoryToolIdempotencyLedger({
      capacity: 3,
      completedTtlMs: 1_000,
      now: () => now,
    });
    for (let index = 0; index < 4; index++) {
      const claim = await ledger.claim("ledger", `call-${index}`, `fingerprint-${index}`);
      expect(claim.status).toBe("owner");
      if (claim.status !== "owner") throw new Error("expected an owner claim");
      await ledger.complete(claim.claim, { index });
      now++;
    }

    expect(await ledger.releaseCompleted("ledger")).toBe(3);
    expect(await ledger.releaseCompleted("ledger")).toBe(0);
  });

  it("never queues more than 1,024 subscriber events and resumes from the cursor", async () => {
    const sessionId = "subscriber";
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const commit = (sequence: number) =>
      committer.commit(
        KajiEvent.parse({
          id: `subscriber-${sequence}`,
          timestamp: 1,
          type: EventType.USER_MESSAGE,
          session_id: sessionId,
          content: String(sequence),
        }),
      );

    await commit(1);
    const slow = committer.subscribe(sessionId);
    expect((await slow.next()).value?.sequence).toBe(1);
    for (let sequence = 2; sequence <= 1_025; sequence++) await commit(sequence);
    await commit(1_026);

    await expect(slow.next()).rejects.toMatchObject({
      code: "EVENT_BUFFER_OVERFLOW",
      lastSequence: 1,
      latestSequence: 1_026,
    });
    const missed = await store.getEvents(sessionId, { afterSequence: 1 });
    expect(missed).toHaveLength(1_025);
    expect(missed[0]?.sequence).toBe(2);
    expect(missed.at(-1)?.sequence).toBe(1_026);

    const resumed = committer.subscribe(sessionId, { afterSequence: 1_025 });
    expect((await resumed.next()).value?.sequence).toBe(1_026);
    await resumed.return?.();
  });

  it("bounds provider context to complete turns and rejects current-turn overflow first", async () => {
    const messages: Message[] = [];
    for (let index = 0; index < 40; index++) {
      messages.push(
        { role: "user", content: `u-${index}-${"u".repeat(1_493)}` },
        { role: "assistant", content: `a-${index}-${"a".repeat(1_493)}` },
      );
    }
    const bounded = buildContext(messages, undefined, DEFAULT_CONTEXT_WINDOW);
    expect(bounded.messages).toHaveLength(64);
    expect(bounded.messages[0]?.role).toBe("user");
    expect(bounded.messages.at(-1)?.role).toBe("assistant");
    expect(
      bounded.messages.reduce((total, message) => total + message.content.length, 0),
    ).toBeLessThanOrEqual(100_000);
    expect(bounded.diagnostics.droppedTurns).toBe(8);

    let providerCalls = 0;
    const provider: ModelProvider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream() {
        providerCalls++;
        yield { delta: "unexpected", toolCalls: [] };
      },
    };
    const { runtime } = runtimeWith(provider);
    await expect(
      runtime.turn("x".repeat(100_001), { sessionId: "context-overflow" }),
    ).rejects.toBeInstanceOf(ContextWindowOverflowError);
    expect(providerCalls).toBe(0);
  });

  it("inspects at most byte 1,048,577 and cancels an oversized registry response", async () => {
    const maxBytes = 1_048_576;
    const chunks = [new Uint8Array(maxBytes), new Uint8Array(1), new Uint8Array(1)];
    let inspectedBytes = 0;
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          const chunk = chunks.shift();
          if (chunk === undefined) {
            controller.close();
            return;
          }
          inspectedBytes += chunk.byteLength;
          controller.enqueue(chunk);
        },
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    const transport: BoundNetworkTransport = {
      async request() {
        return new Response(body);
      },
    };
    const resolver: AddressResolver = async () => ["93.184.216.34"];

    await expect(
      safeRequest(
        new URL("https://example.com/oversized"),
        {},
        toolContext("registry", "oversized"),
        { allowedHosts: ["example.com"] },
        transport,
        resolver,
      ),
    ).rejects.toThrow(/maxResponseBytes/);
    await Promise.resolve();
    expect(inspectedBytes).toBe(maxBytes + 1);
    expect(cancelled).toBe(true);
  });
});
