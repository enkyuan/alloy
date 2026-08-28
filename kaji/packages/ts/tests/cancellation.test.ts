import { describe, expect, it, vi } from "vitest";
import type Anthropic from "@anthropic-ai/sdk";
import type OpenAI from "openai";

import {
  CancellationError,
  CancellationToken,
  createDeadlineCancellationScope,
  throwIfCancellationRequested,
} from "@/runtime/cancellation";
import {
  systemTimerScheduler,
  type Clock,
  type TimerHandle,
  type TimerScheduler,
} from "@/internal/uuid";
import { TurnTimeoutError } from "@/runtime/limits";
import type { ModelResponseChunk } from "@/providers/base";
import { TestAnthropicProvider, TestOpenAIProvider } from "./helpers/provider-clients";

function openAIClient(create: ReturnType<typeof vi.fn>): OpenAI {
  return { chat: { completions: { create } } } as unknown as OpenAI;
}

function anthropicClient(create: ReturnType<typeof vi.fn>): Anthropic {
  return { messages: { create } } as unknown as Anthropic;
}

class ManualClock implements Clock {
  constructor(private monotonic = 0) {}

  nowWallSeconds(): number {
    return 1_700_000_000;
  }

  nowMonotonic(): number {
    return this.monotonic;
  }

  advance(milliseconds: number): void {
    this.monotonic += milliseconds;
  }
}

class ManualScheduler implements TimerScheduler {
  private readonly timers: Array<{
    due: number;
    callback: () => void;
    cancelled: boolean;
  }> = [];

  constructor(private readonly clock: ManualClock) {}

  get pendingCount(): number {
    return this.timers.filter((timer) => !timer.cancelled).length;
  }

  schedule(delayMs: number, callback: () => void): TimerHandle {
    const timer = { due: this.clock.nowMonotonic() + delayMs, callback, cancelled: false };
    this.timers.push(timer);
    return { cancel: () => (timer.cancelled = true) };
  }

  advance(milliseconds: number): void {
    this.clock.advance(milliseconds);
    for (const timer of this.timers) {
      if (!timer.cancelled && timer.due <= this.clock.nowMonotonic()) {
        timer.cancelled = true;
        timer.callback();
      }
    }
  }
}

class ControlledStream implements AsyncIterableIterator<ModelResponseChunk> {
  readonly entered = Promise.withResolvers<void>();
  readonly released = Promise.withResolvers<void>();
  readonly returnEntered = Promise.withResolvers<void>();
  nextActive = false;
  returnCount = 0;
  returnDuringNext = false;
  private yieldedFirst = false;
  private finished = false;

  constructor(
    private readonly token: CancellationToken,
    private readonly firstChunk: boolean,
    private readonly returnGate?: Promise<void>,
  ) {}

  [Symbol.asyncIterator](): AsyncIterableIterator<ModelResponseChunk> {
    return this;
  }

  async next(): Promise<IteratorResult<ModelResponseChunk>> {
    if (this.finished) return { done: true, value: undefined };
    if (this.firstChunk && !this.yieldedFirst) {
      this.yieldedFirst = true;
      return { done: false, value: { delta: "partial", toolCalls: [] } };
    }
    this.nextActive = true;
    this.entered.resolve();
    try {
      await Promise.race([
        this.released.promise,
        new Promise<void>((resolve) => {
          this.token.signal.addEventListener("abort", () => resolve(), { once: true });
        }),
      ]);
      this.finished = true;
      return { done: true, value: undefined };
    } finally {
      this.nextActive = false;
    }
  }

  async return(): Promise<IteratorResult<ModelResponseChunk>> {
    this.returnCount += 1;
    this.returnDuringNext ||= this.nextActive;
    this.returnEntered.resolve();
    await this.returnGate;
    this.finished = true;
    return { done: true, value: undefined };
  }
}

class RejectingStream implements AsyncIterableIterator<ModelResponseChunk> {
  readonly entered = Promise.withResolvers<void>();
  returnCount = 0;

  constructor(
    private readonly token: CancellationToken,
    private readonly error: Error,
    private readonly immediate = false,
  ) {}

  [Symbol.asyncIterator](): AsyncIterableIterator<ModelResponseChunk> {
    return this;
  }

  next(): Promise<IteratorResult<ModelResponseChunk>> {
    this.entered.resolve();
    if (this.immediate) return Promise.reject(this.error);
    return new Promise<IteratorResult<ModelResponseChunk>>((_resolve, reject) => {
      this.token.signal.addEventListener("abort", () => reject(this.error), { once: true });
    });
  }

  async return(): Promise<IteratorResult<ModelResponseChunk>> {
    this.returnCount += 1;
    return { done: true, value: undefined };
  }
}

describe("CancellationToken", () => {
  it("starts not cancelled with a non-aborted signal", () => {
    const t = new CancellationToken();
    expect(t.isCancelled).toBe(false);
    expect(t.signal.aborted).toBe(false);
  });

  it("cancel() flips both isCancelled and signal.aborted", () => {
    const t = new CancellationToken();
    t.cancel();
    expect(t.isCancelled).toBe(true);
    expect(t.signal.aborted).toBe(true);
  });

  it("cancel() is idempotent", () => {
    const t = new CancellationToken();
    t.cancel();
    t.cancel();
    expect(t.isCancelled).toBe(true);
  });

  it("throwIfCancelled raises after cancel", () => {
    const t = new CancellationToken();
    expect(() => t.throwIfCancelled()).not.toThrow();
    t.cancel();
    expect(() => t.throwIfCancelled()).toThrow(CancellationError);
  });

  it("throwIfCancellationRequested raises CancellationError for structural tokens", () => {
    expect(() => throwIfCancellationRequested({ isCancelled: false })).not.toThrow();
    expect(() => throwIfCancellationRequested({ isCancelled: true })).toThrow(CancellationError);
  });

  it("notifies AbortSignal listeners synchronously on cancel", () => {
    const t = new CancellationToken();
    const fired = vi.fn();
    t.signal.addEventListener("abort", fired);
    t.cancel();
    expect(fired).toHaveBeenCalledOnce();
  });
});

describe("DeadlineCancellationScope", () => {
  it("closes a normally completed iterator and disposes its timer and parent listener", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const parent = new CancellationToken();
    const addListener = vi.spyOn(parent.signal, "addEventListener");
    const removeListener = vi.spyOn(parent.signal, "removeEventListener");
    const scope = createDeadlineCancellationScope(parent, 1_000, 2_000, clock, scheduler);
    const stream = new ControlledStream(scope.token, false);
    stream.released.resolve();

    for await (const _chunk of scope.consume(stream)) {
      // The controlled stream completes without output.
    }
    scope.dispose();

    expect(stream.returnCount).toBe(1);
    expect(stream.returnDuringNext).toBe(false);
    expect(addListener).toHaveBeenCalledOnce();
    expect(removeListener).toHaveBeenCalledOnce();
    expect(scheduler.pendingCount).toBe(0);
  });

  it.each([
    { label: "before first output", firstChunk: false, phase: "provider_open" },
    { label: "mid-stream", firstChunk: true, phase: "provider_stream" },
  ] as const)("cancels, joins, and closes exactly once $label", async ({ firstChunk, phase }) => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const parent = new CancellationToken();
    const scope = createDeadlineCancellationScope(parent, 1_000, 2_000, clock, scheduler);
    const stream = new ControlledStream(scope.token, firstChunk);
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        // Drain until the injected deadline fires.
      }
    })();
    await stream.entered.promise;
    scheduler.advance(1_000);

    await expect(consume).rejects.toMatchObject({
      constructor: TurnTimeoutError,
      phase,
      retryable: true,
      outcome: "unknown",
    });
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(stream.returnDuringNext).toBe(false);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("maps provider rejection caused by the owned deadline to TurnTimeoutError", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const scope = createDeadlineCancellationScope(
      new CancellationToken(),
      1_000,
      2_000,
      clock,
      scheduler,
    );
    const raw = new Error("provider rejected its owned cancellation");
    const stream = new RejectingStream(scope.token, raw);
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        // The provider rejects as soon as the owned deadline token aborts.
      }
    })();
    await stream.entered.promise;
    scheduler.advance(1_000);

    await expect(consume).rejects.toMatchObject({
      constructor: TurnTimeoutError,
      phase: "provider_open",
      retryable: true,
      outcome: "unknown",
    });
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("preserves the identity of a provider error settled before the deadline", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const scope = createDeadlineCancellationScope(
      new CancellationToken(),
      1_000,
      2_000,
      clock,
      scheduler,
    );
    const raw = new Error("provider failed first");
    const stream = new RejectingStream(scope.token, raw, true);
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        // The provider fails before the injected clock reaches the deadline.
      }
    })();

    await expect(consume).rejects.toBe(raw);
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(scheduler.pendingCount).toBe(0);
  });

  it.each(["parent", "provider"] as const)(
    "preserves %s cancellation when the provider rejects its owned signal",
    async (source) => {
      const clock = new ManualClock();
      const scheduler = new ManualScheduler(clock);
      const parent = new CancellationToken();
      const scope = createDeadlineCancellationScope(parent, 10_000, 2_000, clock, scheduler);
      const stream = new RejectingStream(
        scope.token,
        source === "parent"
          ? new DOMException("provider rejected cancellation", "AbortError")
          : new Error("provider rejected cancellation"),
      );
      const consume = (async () => {
        for await (const _chunk of scope.consume(stream)) {
          // Drain until cancellation.
        }
      })();
      await stream.entered.promise;
      (source === "parent" ? parent : scope.token).cancel();

      await expect(consume).rejects.toBeInstanceOf(CancellationError);
      scope.dispose();
      expect(stream.returnCount).toBe(1);
      expect(scheduler.pendingCount).toBe(0);
    },
  );

  it("keeps timeout outcome unknown when the deadline fires during consumer work", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const scope = createDeadlineCancellationScope(
      new CancellationToken(),
      1_000,
      2_000,
      clock,
      scheduler,
    );
    const stream = new ControlledStream(scope.token, true);
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        scheduler.advance(1_000);
      }
    })();

    await expect(consume).rejects.toMatchObject({
      constructor: TurnTimeoutError,
      phase: "provider_stream",
      outcome: "unknown",
    });
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("keeps timeout outcome unknown when the deadline fires during iterator close", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const scope = createDeadlineCancellationScope(
      new CancellationToken(),
      1_000,
      2_000,
      clock,
      scheduler,
    );
    const returnGate = Promise.withResolvers<void>();
    const stream = new ControlledStream(scope.token, false, returnGate.promise);
    stream.released.resolve();
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        // This stream completes without output before its slow return.
      }
    })();
    await stream.returnEntered.promise;
    scheduler.advance(1_000);
    await vi.waitFor(() => expect(scheduler.pendingCount).toBe(1));
    returnGate.resolve();

    await expect(consume).rejects.toMatchObject({
      constructor: TurnTimeoutError,
      phase: "provider_open",
      outcome: "unknown",
    });
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(scheduler.pendingCount).toBe(0);
  });

  it("lets caller cancellation win when it fires on the deadline tick", async () => {
    const clock = new ManualClock();
    const scheduler = new ManualScheduler(clock);
    const parent = new CancellationToken();
    const scope = createDeadlineCancellationScope(parent, 1_000, 2_000, clock, scheduler);
    const stream = new ControlledStream(scope.token, false);
    const consume = (async () => {
      for await (const _chunk of scope.consume(stream)) {
        // Drain until cancellation.
      }
    })();
    await stream.entered.promise;
    scheduler.schedule(1_000, () => parent.cancel());
    scheduler.advance(1_000);

    await expect(consume).rejects.toBeInstanceOf(CancellationError);
    scope.dispose();
    expect(stream.returnCount).toBe(1);
    expect(scheduler.pendingCount).toBe(0);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1])(
    "rejects invalid deadlines (%s)",
    (deadline) => {
      const clock = new ManualClock();
      const scheduler = new ManualScheduler(clock);
      expect(() =>
        createDeadlineCancellationScope(new CancellationToken(), deadline, 1, clock, scheduler),
      ).toThrow(/deadlineMonotonicMs/);
    },
  );

  it.each([Number.NaN, Number.POSITIVE_INFINITY, 0, -1])(
    "rejects invalid cancellation grace (%s)",
    (grace) => {
      const clock = new ManualClock();
      const scheduler = new ManualScheduler(clock);
      expect(() =>
        createDeadlineCancellationScope(new CancellationToken(), 1, grace, clock, scheduler),
      ).toThrow(/cancellationGraceMs/);
    },
  );
});

describe("systemTimerScheduler", () => {
  it("rearms deadlines beyond the platform timer maximum and fully cleans up", async () => {
    vi.useFakeTimers();
    const fired = vi.fn();
    const handle = systemTimerScheduler.schedule(2_147_483_657, fired);

    await vi.advanceTimersByTimeAsync(2_147_483_647);
    expect(fired).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(10);
    expect(fired).toHaveBeenCalledOnce();
    handle.cancel();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1])("rejects invalid delays (%s)", (delay) => {
    expect(() => systemTimerScheduler.schedule(delay, () => {})).toThrow(/finite non-negative/);
  });
});

describe("OpenAIProvider AbortSignal plumbing", () => {
  it("passes cancellationToken.signal to the OpenAI client on generate()", async () => {
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok", tool_calls: null } }],
    });
    const provider = new TestOpenAIProvider({ apiKey: "test-key" }, openAIClient(create));

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });

  it("passes signal on generateStream() too", async () => {
    const token = new CancellationToken();
    async function* empty() {} // eslint-disable-line @typescript-eslint/no-empty-function
    const create = vi.fn().mockResolvedValue(empty());
    const provider = new TestOpenAIProvider({ apiKey: "test-key" }, openAIClient(create));

    const iter = provider.generateStream([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });
    // Drain so the inner create() actually runs.
    for await (const _ of iter) {
      void _;
    }

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });

  it("maps token-owned client aborts to CancellationError", async () => {
    const token = new CancellationToken();
    const create = vi.fn().mockImplementation(() => {
      token.cancel();
      return Promise.reject(new Error("aborted"));
    });
    const provider = new TestOpenAIProvider({ apiKey: "test-key" }, openAIClient(create));

    await expect(
      provider.generate([{ role: "user", content: "hi" }], [], {
        cancellationToken: token,
      }),
    ).rejects.toBeInstanceOf(CancellationError);

    expect(create).toHaveBeenCalledOnce();
  });
});

describe("AnthropicProvider AbortSignal plumbing", () => {
  it("passes cancellationToken.signal to the Anthropic client on generate()", async () => {
    const token = new CancellationToken();
    const create = vi.fn().mockResolvedValue({ content: [{ type: "text", text: "ok" }] });
    const provider = new TestAnthropicProvider({ apiKey: "test-key" }, anthropicClient(create));

    await provider.generate([{ role: "user", content: "hi" }], [], {
      cancellationToken: token,
    });

    expect(create).toHaveBeenCalledOnce();
    const [, requestOpts] = create.mock.calls[0]!;
    expect(requestOpts).toEqual({ signal: token.signal });
  });

  it("maps token-owned client aborts to CancellationError", async () => {
    const token = new CancellationToken();
    const create = vi.fn().mockImplementation(() => {
      token.cancel();
      return Promise.reject(new Error("aborted"));
    });
    const provider = new TestAnthropicProvider({ apiKey: "test-key" }, anthropicClient(create));

    await expect(
      provider.generate([{ role: "user", content: "hi" }], [], {
        cancellationToken: token,
      }),
    ).rejects.toBeInstanceOf(CancellationError);

    expect(create).toHaveBeenCalledOnce();
  });
});
