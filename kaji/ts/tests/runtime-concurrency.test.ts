import { describe, expect, expectTypeOf, it } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import type { NewKajiEvent, StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "@/providers/base";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import { AgentBuilder } from "@/runtime/builder";
import { AgentRuntime } from "@/runtime/runtime";
import {
  InMemorySessionTurnCoordinator,
  type ObservableCancellationToken,
  type SessionTurnCoordinator,
} from "@/runtime/session-turn-coordinator";
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

class BarrierProvider implements ModelProvider {
  private readonly entered = new Map<string, Deferred>();
  private readonly releases = new Map<string, Deferred>();
  private readonly enteredPrompts = new Set<string>();
  private readonly active = new Map<string, number>();
  private readonly maximum = new Map<string, number>();

  constructor(
    private readonly sessions: Record<string, string>,
    private readonly failures = new Set<string>(),
  ) {
    for (const prompt of Object.keys(sessions)) {
      this.entered.set(prompt, new Deferred());
      this.releases.set(prompt, new Deferred());
    }
  }

  activeFor(sessionId: string): number {
    return this.active.get(sessionId) ?? 0;
  }

  maximumFor(sessionId: string): number {
    return this.maximum.get(sessionId) ?? 0;
  }

  hasEntered(prompt: string): boolean {
    return this.enteredPrompts.has(prompt);
  }

  waitUntilEntered(prompt: string): Promise<void> {
    return this.entered.get(prompt)!.promise;
  }

  release(prompt: string): void {
    this.releases.get(prompt)!.resolve();
  }

  async generate(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): Promise<ModelResponse> {
    throw new Error("BarrierProvider only supports streaming");
  }

  async *generateStream(
    messages: ProviderMessage[],
    _tools: ToolSpec[],
    _options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    const prompt = [...messages].reverse().find((message) => message.role === "user")?.content;
    if (prompt === undefined || this.sessions[prompt] === undefined) {
      throw new Error(`Unexpected prompt ${prompt ?? "<missing>"}`);
    }
    const sessionId = this.sessions[prompt];
    const active = this.activeFor(sessionId) + 1;
    this.active.set(sessionId, active);
    this.maximum.set(sessionId, Math.max(this.maximumFor(sessionId), active));
    this.enteredPrompts.add(prompt);
    this.entered.get(prompt)!.resolve();
    try {
      await this.releases.get(prompt)!.promise;
      if (this.failures.has(prompt)) {
        throw new Error(`provider failed for ${prompt} with secret-token`);
      }
      yield { delta: `reply:${prompt}`, toolCalls: [] };
    } finally {
      this.active.set(sessionId, this.activeFor(sessionId) - 1);
    }
  }
}

class ObservedCoordinator implements SessionTurnCoordinator {
  calls = 0;
  readonly secondAttempted = new Deferred();

  constructor(readonly inner: InMemorySessionTurnCoordinator) {}

  runExclusive<T>(
    sessionId: string,
    token: ObservableCancellationToken | undefined,
    operation: () => Promise<T>,
  ): Promise<T> {
    this.calls += 1;
    const result = this.inner.runExclusive(sessionId, token, operation);
    if (this.calls === 2) this.secondAttempted.resolve();
    return result;
  }
}

function runtimeWith(
  provider: ModelProvider,
  coordinator: SessionTurnCoordinator,
): { runtime: AgentRuntime; store: InMemoryEventStore } {
  const store = new InMemoryEventStore();
  return {
    store,
    runtime: new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      turnCoordinator: coordinator,
      tools: [],
    }),
  };
}

function expectOneTurn(events: StoredKajiEvent[], turnId: string): void {
  expect(events.length).toBeGreaterThan(0);
  expect(events.every((event) => event.turn_id === turnId)).toBe(true);
}

describe("session turn coordination", () => {
  it("requires observable cancellation in the public coordinator contract", () => {
    expectTypeOf<ObservableCancellationToken["signal"]>().toEqualTypeOf<AbortSignal>();
    expectTypeOf<Parameters<SessionTurnCoordinator["runExclusive"]>[1]>().toEqualTypeOf<
      ObservableCancellationToken | undefined
    >();
  });

  it("serializes same-session turns and scopes results by turn id", async () => {
    const provider = new BarrierProvider({ A: "same", B: "same" });
    const observed = new ObservedCoordinator(new InMemorySessionTurnCoordinator());
    const { runtime, store } = runtimeWith(provider, observed);

    const first = runtime.turn("A", { sessionId: "same" });
    await provider.waitUntilEntered("A");
    const second = runtime.turn("B", { sessionId: "same" });
    await observed.secondAttempted.promise;

    expect(provider.activeFor("same")).toBe(1);
    expect(provider.hasEntered("B")).toBe(false);

    provider.release("A");
    const firstResult = await first;
    await provider.waitUntilEntered("B");
    provider.release("B");
    const secondResult = await second;

    expect(firstResult.text).toBe("reply:A");
    expect(secondResult.text).toBe("reply:B");
    expect(firstResult.turnId).not.toBe(secondResult.turnId);
    expectOneTurn(firstResult.events, firstResult.turnId);
    expectOneTurn(secondResult.events, secondResult.turnId);
    expect(provider.maximumFor("same")).toBe(1);
    expect(
      (await store.getEvents("same")).filter((event) => event.type === EventType.SESSION_CREATED),
    ).toHaveLength(1);
    expect(observed.calls).toBe(2);
    expect(observed.inner.entryCount).toBe(0);
  });

  it("allows different sessions to overlap", async () => {
    const provider = new BarrierProvider({ X: "one", Y: "two" });
    const coordinator = new InMemorySessionTurnCoordinator();
    const { runtime } = runtimeWith(provider, coordinator);

    const one = runtime.turn("X", { sessionId: "one" });
    const two = runtime.turn("Y", { sessionId: "two" });
    await Promise.all([provider.waitUntilEntered("X"), provider.waitUntilEntered("Y")]);

    expect(provider.activeFor("one")).toBe(1);
    expect(provider.activeFor("two")).toBe(1);
    provider.release("X");
    provider.release("Y");
    await Promise.all([one, two]);
    expect(coordinator.entryCount).toBe(0);
  });

  it("acquires exactly once for each public turn, send, and run path", async () => {
    const provider = new BarrierProvider({ T: "turn", S: "send" });
    const observed = new ObservedCoordinator(new InMemorySessionTurnCoordinator());
    const store = new InMemoryEventStore();
    const runtime = new AgentBuilder().provider(provider).build({
      store,
      turnCoordinator: observed,
    });

    const turn = runtime.turn("T", { sessionId: "turn" });
    await provider.waitUntilEntered("T");
    provider.release("T");
    await turn;
    expect(observed.calls).toBe(1);

    const send = runtime.send("send", "S");
    await provider.waitUntilEntered("S");
    provider.release("S");
    await send;
    expect(observed.calls).toBe(2);

    await runtime.runTurn("send");
    expect(observed.calls).toBe(3);
    const turnIds = new Set((await store.getEvents("send")).map((event) => event.turn_id));
    expect(turnIds.has(undefined)).toBe(false);
    expect(turnIds.size).toBe(2);
    expect(observed.inner.entryCount).toBe(0);
  });

  it("acquires queued work in FIFO order", async () => {
    const coordinator = new InMemorySessionTurnCoordinator();
    const firstEntered = new Deferred();
    const secondEntered = new Deferred();
    const thirdEntered = new Deferred();
    const releaseFirst = new Deferred();
    const releaseSecond = new Deferred();
    const order: number[] = [];

    const first = coordinator.runExclusive("fifo", undefined, async () => {
      order.push(1);
      firstEntered.resolve();
      await releaseFirst.promise;
    });
    await firstEntered.promise;
    const second = coordinator.runExclusive("fifo", undefined, async () => {
      order.push(2);
      secondEntered.resolve();
      await releaseSecond.promise;
    });
    const third = coordinator.runExclusive("fifo", undefined, async () => {
      order.push(3);
      thirdEntered.resolve();
    });

    releaseFirst.resolve();
    await secondEntered.promise;
    expect(order).toEqual([1, 2]);
    releaseSecond.resolve();
    await thirdEntered.promise;
    await Promise.all([first, second, third]);
    expect(order).toEqual([1, 2, 3]);
    expect(coordinator.entryCount).toBe(0);
  });

  it("cleans up cancellation before acquisition and while waiting or held", async () => {
    const coordinator = new InMemorySessionTurnCoordinator();
    const cancelledBefore = new CancellationToken();
    cancelledBefore.cancel();
    let ran = false;
    await expect(
      coordinator.runExclusive("before", cancelledBefore, async () => {
        ran = true;
      }),
    ).rejects.toBeInstanceOf(CancellationError);
    expect(ran).toBe(false);
    expect(coordinator.entryCount).toBe(0);

    const holderEntered = new Deferred();
    const releaseHolder = new Deferred();
    const holder = coordinator.runExclusive("waiting", undefined, async () => {
      holderEntered.resolve();
      await releaseHolder.promise;
    });
    await holderEntered.promise;
    const waitingToken = new CancellationToken();
    const waiting = coordinator.runExclusive("waiting", waitingToken, async () => {
      ran = true;
    });
    const waitingRejection = expect(waiting).rejects.toBeInstanceOf(CancellationError);
    waitingToken.cancel();
    await waitingRejection;
    expect(coordinator.entryCount).toBe(1);
    releaseHolder.resolve();
    await holder;
    expect(coordinator.entryCount).toBe(0);

    const runningToken = new CancellationToken();
    const runningEntered = new Deferred();
    const running = coordinator.runExclusive("held", runningToken, async () => {
      runningEntered.resolve();
      await new Promise<void>((resolve) =>
        runningToken.signal.addEventListener("abort", () => resolve(), { once: true }),
      );
      runningToken.throwIfCancelled();
    });
    await runningEntered.promise;
    const runningRejection = expect(running).rejects.toBeInstanceOf(CancellationError);
    runningToken.cancel();
    await runningRejection;
    expect(coordinator.entryCount).toBe(0);
  });

  it("rejects an unobservable cancellation token before it can queue", async () => {
    const coordinator = new InMemorySessionTurnCoordinator();
    const holderEntered = new Deferred();
    const releaseHolder = new Deferred();
    const holder = coordinator.runExclusive("unobservable", undefined, async () => {
      holderEntered.resolve();
      await releaseHolder.promise;
    });
    await holderEntered.promise;

    let ran = false;
    const unobservable = {
      isCancelled: false,
    } as unknown as ObservableCancellationToken;
    await expect(
      coordinator.runExclusive("unobservable", unobservable, async () => {
        ran = true;
      }),
    ).rejects.toThrow("requires an AbortSignal");
    expect(ran).toBe(false);
    expect(coordinator.waitingCount).toBe(0);
    expect(coordinator.entryCount).toBe(1);

    releaseHolder.resolve();
    await holder;
    expect(coordinator.entryCount).toBe(0);
  });

  it("actively unlinks many cancelled waiters behind a held session", async () => {
    const coordinator = new InMemorySessionTurnCoordinator();
    const holderEntered = new Deferred();
    const releaseHolder = new Deferred();
    const holder = coordinator.runExclusive("cancel-many", undefined, async () => {
      holderEntered.resolve();
      await releaseHolder.promise;
    });
    await holderEntered.promise;

    const tokens = Array.from({ length: 64 }, () => new CancellationToken());
    const waiters = tokens.map((token) =>
      coordinator.runExclusive("cancel-many", token, async () => {
        throw new Error("cancelled waiter unexpectedly ran");
      }),
    );
    expect(coordinator.waitingCount).toBe(tokens.length);
    const settled = Promise.all(waiters.map((waiter) => waiter.catch((error) => error)));

    for (const token of tokens) token.cancel();
    const errors = await settled;
    expect(errors.every((error) => error instanceof CancellationError)).toBe(true);
    expect(coordinator.waitingCount).toBe(0);
    expect(coordinator.entryCount).toBe(1);

    releaseHolder.resolve();
    await holder;
    expect(coordinator.entryCount).toBe(0);
  });

  it("releases after provider and operation errors", async () => {
    const provider = new BarrierProvider({ bad: "errors", good: "errors" }, new Set(["bad"]));
    const coordinator = new InMemorySessionTurnCoordinator();
    const { runtime, store } = runtimeWith(provider, coordinator);

    const bad = runtime.turn("bad", { sessionId: "errors" });
    await provider.waitUntilEntered("bad");
    provider.release("bad");
    await expect(bad).rejects.toThrow("provider failed for bad with secret-token");
    const firstEvents = await store.getEvents("errors");
    const failedEvents = firstEvents.filter((event) => event.type === EventType.AGENT_TURN_FAILED);
    expect(failedEvents).toHaveLength(1);
    const failure = failedEvents[0]!;
    expect("error" in failure ? failure.error : undefined).toBe("Agent turn failed");
    expect(JSON.stringify(failure)).not.toContain("secret-token");
    expect(failure.turn_id).toBeTruthy();
    expect(firstEvents.every((event) => event.turn_id === failure.turn_id)).toBe(true);
    expect(coordinator.entryCount).toBe(0);

    const good = runtime.turn("good", { sessionId: "errors" });
    await provider.waitUntilEntered("good");
    provider.release("good");
    await expect(good).resolves.toMatchObject({ text: "reply:good" });
    const completedTurns = new Set((await store.getEvents("errors")).map((event) => event.turn_id));
    expect(completedTurns.size).toBe(2);
    expect(coordinator.entryCount).toBe(0);

    await expect(
      coordinator.runExclusive("throw", undefined, async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    await expect(
      coordinator.runExclusive("throw", undefined, async () => "released"),
    ).resolves.toBe("released");
    expect(coordinator.entryCount).toBe(0);
  });

  it("preserves the provider error when terminal failure persistence also fails", async () => {
    const original = new Error("original provider failure");
    const provider: ModelProvider = {
      async generate(): Promise<ModelResponse> {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        throw original;
        yield { delta: "unreachable", toolCalls: [] };
      },
    };
    const store = new InMemoryEventStore();
    const coordinator = new InMemorySessionTurnCoordinator();
    class FailingTerminalCommitter extends InMemoryEventCommitter {
      override commit(event: NewKajiEvent): Promise<StoredKajiEvent> {
        if (event.type === EventType.AGENT_TURN_FAILED) {
          return Promise.reject(new Error("terminal failure commit failed"));
        }
        return super.commit(event);
      }
    }
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new FailingTerminalCommitter(store),
      turnCoordinator: coordinator,
      tools: [],
    });

    await expect(runtime.turn("fail", { sessionId: "failure-commit" })).rejects.toBe(original);
    expect(coordinator.entryCount).toBe(0);
  });

  it("does not misclassify a real error when cancellation races with it", async () => {
    const original = new Error("real provider failure");
    const token = new CancellationToken();
    const provider: ModelProvider = {
      async generate(): Promise<ModelResponse> {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        token.cancel();
        throw original;
        yield { delta: "unreachable", toolCalls: [] };
      },
    };
    const coordinator = new InMemorySessionTurnCoordinator();
    const { runtime, store } = runtimeWith(provider, coordinator);

    await expect(
      runtime.turn("race", { sessionId: "error-cancel-race", cancellationToken: token }),
    ).rejects.toBe(original);

    const types = (await store.getEvents("error-cancel-race")).map((event) => event.type);
    expect(types).toContain(EventType.AGENT_TURN_FAILED);
    expect(types).not.toContain(EventType.CANCELLATION_COMPLETED);
    expect(coordinator.entryCount).toBe(0);
  });

  it("recognizes a fetch-style abort only when its owned token is cancelled", async () => {
    const token = new CancellationToken();
    const provider: ModelProvider = {
      async generate(): Promise<ModelResponse> {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        token.cancel();
        throw new DOMException("The operation was aborted", "AbortError");
        yield { delta: "unreachable", toolCalls: [] };
      },
    };
    const coordinator = new InMemorySessionTurnCoordinator();
    const { runtime, store } = runtimeWith(provider, coordinator);

    await expect(
      runtime.turn("abort", { sessionId: "owned-fetch-abort", cancellationToken: token }),
    ).resolves.toMatchObject({ sessionId: "owned-fetch-abort" });

    const types = (await store.getEvents("owned-fetch-abort")).map((event) => event.type);
    expect(types).toContain(EventType.CANCELLATION_COMPLETED);
    expect(types).not.toContain(EventType.AGENT_TURN_FAILED);
    expect(coordinator.entryCount).toBe(0);

    const unownedAbort = new DOMException("The operation was aborted", "AbortError");
    const unownedProvider: ModelProvider = {
      async generate(): Promise<ModelResponse> {
        return { content: "", toolCalls: [] };
      },
      async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        throw unownedAbort;
        yield { delta: "unreachable", toolCalls: [] };
      },
    };
    const unownedCoordinator = new InMemorySessionTurnCoordinator();
    const { runtime: unownedRuntime, store: unownedStore } = runtimeWith(
      unownedProvider,
      unownedCoordinator,
    );

    await expect(unownedRuntime.turn("abort", { sessionId: "unowned-fetch-abort" })).rejects.toBe(
      unownedAbort,
    );
    const unownedTypes = (await unownedStore.getEvents("unowned-fetch-abort")).map(
      (event) => event.type,
    );
    expect(unownedTypes).toContain(EventType.AGENT_TURN_FAILED);
    expect(unownedTypes).not.toContain(EventType.CANCELLATION_COMPLETED);
    expect(unownedCoordinator.entryCount).toBe(0);
  });

  it("shares the default coordinator per store without cross-store blocking", async () => {
    const sharedStore = new InMemoryEventStore();
    const sharedProvider = new BarrierProvider({ A: "shared", B: "shared" });
    const firstRuntime = new AgentBuilder().provider(sharedProvider).build({
      store: sharedStore,
    });
    const secondRuntime = new AgentBuilder().provider(sharedProvider).build({
      store: sharedStore,
    });

    const first = firstRuntime.turn("A", { sessionId: "shared" });
    await sharedProvider.waitUntilEntered("A");
    const second = secondRuntime.turn("B", { sessionId: "shared" });
    expect(sharedProvider.hasEntered("B")).toBe(false);
    sharedProvider.release("A");
    await sharedProvider.waitUntilEntered("B");
    sharedProvider.release("B");
    await Promise.all([first, second]);

    expect(sharedProvider.maximumFor("shared")).toBe(1);
    expect(
      (await sharedStore.getEvents("shared")).filter(
        (event) => event.type === EventType.SESSION_CREATED,
      ),
    ).toHaveLength(1);

    const leftStore = new InMemoryEventStore();
    const rightStore = new InMemoryEventStore();
    const independentProvider = new BarrierProvider({ left: "same", right: "same" });
    const leftRuntime = new AgentBuilder().provider(independentProvider).build({
      store: leftStore,
    });
    const rightRuntime = new AgentBuilder().provider(independentProvider).build({
      store: rightStore,
    });

    const left = leftRuntime.turn("left", { sessionId: "same" });
    const right = rightRuntime.turn("right", { sessionId: "same" });
    await Promise.all([
      independentProvider.waitUntilEntered("left"),
      independentProvider.waitUntilEntered("right"),
    ]);
    expect(independentProvider.activeFor("same")).toBe(2);
    independentProvider.release("left");
    independentProvider.release("right");
    await Promise.all([left, right]);
  });
});
