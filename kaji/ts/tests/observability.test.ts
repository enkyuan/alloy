import { describe, expect, it, vi } from "vitest";

import {
  NOOP_METRICS,
  NOOP_TRACE,
  METRIC_NAMES,
  providerFamily,
  recordMetric,
  startSpan,
  type MetricMeasurement,
  type MetricsSink,
  type TraceSink,
} from "@/observability";
import { MockProvider } from "@/providers/mock";
import { openStreamWithRetry, withRetry } from "@/providers/base";
import { AgentBuilder } from "@/runtime/builder";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import { buildContext } from "@/runtime/context";
import { ToolExecutionController } from "@/tools/execution";
import { InMemoryEventCommitter, SplitEventCommitter } from "@/events/committer";
import { EventBus } from "@/events/bus";
import { KajiEvent, type NewKajiEvent, type StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore, type AppendResult } from "@/events/store";
import { EventType } from "@/events/types";

describe("observability contracts", () => {
  it("records the closed metric vocabulary and strips undeclared labels", () => {
    const measurements: MetricMeasurement[] = [];
    const sink: MetricsSink = {
      record: (measurement) => {
        measurements.push(measurement);
      },
    };
    const secret = "sk-secret";

    recordMetric(sink, "kaji.provider.duration_ms", 12, {
      provider_family: "openai",
      status: "success",
      session_id: secret,
    } as never);

    expect(measurements).toEqual([
      {
        name: "kaji.provider.duration_ms",
        value: 12,
        unit: "ms",
        labels: { provider_family: "openai", status: "success" },
      },
    ]);
    expect(JSON.stringify(measurements)).not.toContain(secret);
  });

  it("exports exactly the fourteen stable metric names", () => {
    expect(METRIC_NAMES).toEqual([
      "kaji.turn.queue_wait_ms",
      "kaji.turn.duration_ms",
      "kaji.turn.iterations",
      "kaji.provider.duration_ms",
      "kaji.provider.retries",
      "kaji.replay.input_events",
      "kaji.context.messages",
      "kaji.context.characters",
      "kaji.tool.queue_wait_ms",
      "kaji.tool.active",
      "kaji.tool.duration_ms",
      "kaji.journal.failures",
      "kaji.subscriber.lag_events",
      "kaji.subscriber.overflow",
    ]);
  });

  it("normalizes custom provider names and unknown error codes", () => {
    const measurements: MetricMeasurement[] = [];
    const sink: MetricsSink = {
      record: (measurement) => {
        measurements.push(measurement);
      },
    };

    recordMetric(sink, "kaji.provider.duration_ms", 1, {
      provider_family: "private-provider",
      status: "private-status",
    } as never);
    recordMetric(sink, "kaji.tool.duration_ms", 2, {
      outcome: "failed",
      error_code: "USER_SPECIFIC_ERROR_123",
    });

    expect(measurements[0]?.labels).toEqual({ provider_family: "custom", status: "error" });
    expect(measurements[1]?.labels).toEqual({ outcome: "failed", error_code: "OTHER" });
    expect(providerFamily({})).toBe("custom");
    expect(providerFamily({ providerFamily: "anthropic" })).toBe("anthropic");
    expect(
      providerFamily(
        Object.defineProperty({}, "providerFamily", {
          get() {
            throw new Error("unsafe getter");
          },
        }),
      ),
    ).toBe("custom");
  });

  it("isolates synchronous and asynchronous sink failures", async () => {
    expect(() =>
      recordMetric(
        { record: () => Promise.reject(new Error("metric failure")) },
        "kaji.context.messages",
        1,
        {},
      ),
    ).not.toThrow();
    expect(() =>
      recordMetric(
        {
          record: () => {
            throw new Error("metric failure");
          },
        },
        "kaji.context.messages",
        1,
        {},
      ),
    ).not.toThrow();
    await Promise.resolve();
  });

  it("protects callers from throwing spans and ends spans idempotently", () => {
    const end = vi.fn(() => {
      throw new Error("trace failure");
    });
    const sink: TraceSink = {
      startSpan: () => ({
        setAttribute: () => {
          throw new Error("trace failure");
        },
        recordError: () => {
          throw new Error("trace failure");
        },
        end,
      }),
    };
    const span = startSpan(sink, "kaji.turn", { "session.id": "s" });
    expect(() => span.setAttribute("turn.id", "t")).not.toThrow();
    expect(() => span.recordError(new Error("private"))).not.toThrow();
    expect(() => span.end()).not.toThrow();
    span.end();
    expect(end).toHaveBeenCalledOnce();
  });

  it("drops runtime-unsafe span names and attribute keys", () => {
    const start = vi.fn(() => ({ setAttribute: vi.fn(), recordError: vi.fn(), end: vi.fn() }));
    const sink: TraceSink = { startSpan: start };
    startSpan(sink, "private.span" as never).end();
    startSpan(sink, "kaji.turn", { prompt: "secret" } as never).end();
    expect(start).not.toHaveBeenCalled();
  });

  it("provides allocation-bounded no-op defaults", () => {
    expect(() => recordMetric(NOOP_METRICS, "kaji.tool.active", 0, {})).not.toThrow();
    const span = startSpan(NOOP_TRACE, "kaji.turn");
    span.setAttribute("trace.id", "trace");
    span.recordError(new Error("ignored"));
    span.end();
  });

  it("wires turn, replay, context, provider, and tool measurements without payload labels", async () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    let tick = 0;
    const now = () => ++tick;
    const secret = "secret prompt and tool argument";
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "done" }))
      .metricsSink(metrics)
      .monotonicClock(now)
      .build();

    await runtime.turn(secret, {
      context: {
        principalId: "principal",
        requestId: "request",
        traceId: "trace",
      },
    });

    const controller = new ToolExecutionController({ metricsSink: metrics, monotonicNow: now });
    const signal = new AbortController().signal;
    await controller.execute({
      name: "secret-tool-name",
      args: { secret },
      context: {
        principalId: "principal",
        sessionId: "tool-session",
        turnId: "tool-turn",
        requestId: "tool-request",
        traceId: "tool-trace",
        toolCallId: "tool-call",
        idempotencyKey: "tool-session:tool-call",
        signal,
        metadata: {},
      },
      exclusive: false,
      onStarted: async () => {},
      execute: async () => ({ ok: true }),
    });

    const names = new Set(measurements.map((measurement) => measurement.name));
    for (const expected of [
      "kaji.turn.queue_wait_ms",
      "kaji.turn.duration_ms",
      "kaji.turn.iterations",
      "kaji.provider.duration_ms",
      "kaji.replay.input_events",
      "kaji.context.messages",
      "kaji.context.characters",
      "kaji.tool.queue_wait_ms",
      "kaji.tool.active",
      "kaji.tool.duration_ms",
    ]) {
      expect(names.has(expected as never)).toBe(true);
    }
    expect(JSON.stringify(measurements)).not.toContain(secret);
    expect(JSON.stringify(measurements)).not.toContain("secret-tool-name");
    expect(JSON.stringify(measurements)).not.toContain("principal");

    let attempts = 0;
    await withRetry(
      async () => {
        attempts += 1;
        if (attempts === 1) throw Object.assign(new Error("rate limited"), { status: 429 });
        return "ok";
      },
      { maxAttempts: 2, baseDelayMs: 0 },
      undefined,
      metrics,
      "openai",
    );

    const healthy = new InMemoryEventStore();
    const failingStore = {
      maxSessions: healthy.maxSessions,
      append: async (_event: NewKajiEvent): Promise<AppendResult> => {
        throw new Error("append unavailable");
      },
      getEvents: healthy.getEvents.bind(healthy),
      lastSequence: healthy.lastSequence.bind(healthy),
    };
    const failingCommitter = new InMemoryEventCommitter(failingStore, { metricsSink: metrics });
    await expect(
      failingCommitter.commit(
        KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "failed" }),
      ),
    ).rejects.toThrow();

    const buffered = new InMemoryEventCommitter(new InMemoryEventStore(), {
      subscriberCapacity: 1,
      metricsSink: metrics,
    });
    const subscriber = buffered.subscribe("buffered");
    const first = subscriber.next();
    await buffered.commit(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "buffered" }),
    );
    await first;
    await buffered.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "buffered", content: "one" }),
    );
    await buffered.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "buffered", content: "two" }),
    );
    await expect(subscriber.next()).rejects.toThrow(/overflow/i);

    for (const expected of [
      "kaji.provider.retries",
      "kaji.journal.failures",
      "kaji.subscriber.lag_events",
      "kaji.subscriber.overflow",
    ]) {
      expect(measurements.some((measurement) => measurement.name === expected)).toBe(true);
    }
  });

  it("counts Unicode and structured provider context payloads semantically", () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    buildContext(
      [
        {
          role: "assistant",
          content: "a",
          toolCalls: [{ id: "c", name: "tool", args: { emoji: "😀" } }],
        },
        { role: "tool", content: "ok", name: "tool", toolCallId: "c" },
      ],
      "😀",
      undefined,
      metrics,
    );
    const codePoints = (value: string) => Array.from(value).length;
    const expected =
      codePoints("😀") +
      codePoints("a") +
      codePoints("c") +
      codePoints("tool") +
      codePoints('{"emoji":"😀"}') +
      codePoints("ok") +
      codePoints("tool") +
      codePoints("c");
    expect(
      measurements.find((measurement) => measurement.name === "kaji.context.characters")?.value,
    ).toBe(expected);
  });

  it("keeps throwing runtime sinks observational", async () => {
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "done" }))
      .metricsSink({
        record() {
          throw new Error("sink unavailable");
        },
      })
      .traceSink({
        startSpan() {
          throw new Error("sink unavailable");
        },
      })
      .build();
    await expect(runtime.turn("hello")).resolves.toMatchObject({ text: "done" });
  });

  it("keeps throwing sinks observational for tools, journals, and subscribers", async () => {
    const throwing: MetricsSink = {
      record() {
        throw new Error("sink unavailable");
      },
    };
    const controller = new ToolExecutionController({ metricsSink: throwing });
    await expect(
      controller.execute({
        name: "tool",
        args: {},
        context: {
          principalId: "principal",
          sessionId: "session",
          turnId: "turn",
          requestId: "request",
          traceId: "trace",
          toolCallId: "call",
          idempotencyKey: "session:call",
          signal: new AbortController().signal,
          metadata: {},
        },
        exclusive: false,
        onStarted: async () => {},
        execute: async () => "ok",
      }),
    ).resolves.toMatchObject({ status: "completed", result: "ok" });

    const committer = new InMemoryEventCommitter(new InMemoryEventStore(), {
      subscriberCapacity: 1,
      metricsSink: throwing,
    });
    const subscriber = committer.subscribe("subscriber");
    const first = subscriber.next();
    await committer.commit(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "subscriber" }),
    );
    await first;
    await committer.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "subscriber", content: "one" }),
    );
    await committer.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "subscriber", content: "two" }),
    );
    await expect(subscriber.next()).rejects.toThrow(/overflow/i);

    const healthy = new InMemoryEventStore();
    const failingCommitter = new InMemoryEventCommitter(
      {
        maxSessions: healthy.maxSessions,
        append: async (_event: NewKajiEvent): Promise<AppendResult> => {
          throw new Error("journal unavailable");
        },
        getEvents: healthy.getEvents.bind(healthy),
        lastSequence: healthy.lastSequence.bind(healthy),
      },
      { metricsSink: throwing },
    );
    await expect(
      failingCommitter.commit(
        KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "journal" }),
      ),
    ).rejects.toThrow(/append failed/i);
  });

  it("records start acknowledgement failures with their stable code", async () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const cause = new Error("journal unavailable");
    const controller = new ToolExecutionController({ metricsSink: metrics });
    await expect(
      controller.execute({
        name: "tool",
        args: {},
        context: {
          principalId: "principal",
          sessionId: "session",
          turnId: "turn",
          requestId: "request",
          traceId: "trace",
          toolCallId: "call",
          idempotencyKey: "session:call",
          signal: new AbortController().signal,
          metadata: {},
        },
        exclusive: false,
        onStarted: async () => {
          throw cause;
        },
        execute: async () => ({ ok: true }),
      }),
    ).rejects.toBe(cause);
    expect(
      measurements.find((measurement) => measurement.name === "kaji.tool.duration_ms")?.labels,
    ).toEqual({ outcome: "not_started", error_code: "TOOL_START_RECORD_FAILED" });
  });

  it("retries streams only before the first item and records the retry", async () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    let attempts = 0;
    const stream = await openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]: async function* () {
          attempts += 1;
          if (attempts === 1) {
            throw Object.assign(new Error("rate limited"), { status: 429 });
          }
          yield "first";
          yield "second";
        },
      }),
      { maxAttempts: 2, baseDelayMs: 0 },
      undefined,
      metrics,
      "anthropic",
    );
    const values: string[] = [];
    for await (const value of stream) values.push(value);
    expect(values).toEqual(["first", "second"]);
    expect(attempts).toBe(2);
    expect(
      measurements.filter((measurement) => measurement.name === "kaji.provider.retries"),
    ).toHaveLength(1);

    let partialAttempts = 0;
    const partial = await openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]: async function* () {
          partialAttempts += 1;
          yield "already-visible";
          throw Object.assign(new Error("late rate limit"), { status: 429 });
        },
      }),
      { maxAttempts: 3, baseDelayMs: 0 },
      undefined,
      metrics,
      "openai",
    );
    const iterator = partial[Symbol.asyncIterator]();
    await expect(iterator.next()).resolves.toMatchObject({ value: "already-visible", done: false });
    await expect(iterator.next()).rejects.toThrow("late rate limit");
    expect(partialAttempts).toBe(1);

    const cancellation = new CancellationToken();
    let cancelledAttempts = 0;
    const opening = openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]: async function* () {
          cancelledAttempts += 1;
          throw Object.assign(new Error("rate limited"), { status: 429 });
        },
      }),
      { maxAttempts: 3, baseDelayMs: 10_000 },
      cancellation,
      metrics,
      "openai",
    );
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    cancellation.cancel();
    await expect(opening).rejects.toBeInstanceOf(CancellationError);
    expect(cancelledAttempts).toBe(1);
  });

  it("closes a retry-opened stream before wrapper iteration and does not read past done", async () => {
    let nextCalls = 0;
    let returnCalls = 0;
    const earlyReturn = await openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]() {
          return {
            next: async () => {
              nextCalls += 1;
              return { value: "buffered", done: false } as const;
            },
            return: async () => {
              returnCalls += 1;
              return { value: undefined, done: true } as const;
            },
          };
        },
      }),
      { maxAttempts: 1, baseDelayMs: 0 },
    );
    await earlyReturn.return?.();
    expect(nextCalls).toBe(1);
    expect(returnCalls).toBe(1);
    await expect(earlyReturn.next()).resolves.toMatchObject({ done: true });

    let throwReturns = 0;
    const earlyThrow = await openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]() {
          return {
            next: async () => ({ value: "buffered", done: false }) as const,
            return: async () => {
              throwReturns += 1;
              return { value: undefined, done: true } as const;
            },
          };
        },
      }),
      { maxAttempts: 1, baseDelayMs: 0 },
    );
    const stop = new Error("stop");
    await expect(earlyThrow.throw?.(stop)).rejects.toBe(stop);
    expect(throwReturns).toBe(1);

    let doneNextCalls = 0;
    const alreadyDone = await openStreamWithRetry(
      () => ({
        [Symbol.asyncIterator]() {
          return {
            next: async () => {
              doneNextCalls += 1;
              return { value: undefined, done: true } as const;
            },
          };
        },
      }),
      { maxAttempts: 1, baseDelayMs: 0 },
    );
    await expect(alreadyDone.next()).resolves.toMatchObject({ done: true });
    expect(doneNextCalls).toBe(1);
  });

  it("counts a shared split-bus live overflow exactly once", async () => {
    const measurements: MetricMeasurement[] = [];
    const metrics: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const store = new InMemoryEventStore();
    const bus = new EventBus<StoredKajiEvent>(1, metrics);
    const committer = new SplitEventCommitter(store, bus, {
      subscriberCapacity: 10,
      metricsSink: metrics,
    });
    const subscriber = committer.subscribe("shared");
    const first = subscriber.next();
    await committer.commit(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "shared" }),
    );
    await first;
    await committer.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "shared", content: "one" }),
    );
    await committer.commit(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "shared", content: "two" }),
    );

    await expect(subscriber.next()).rejects.toThrow(/overflow/i);
    expect(
      measurements.filter(
        (measurement) =>
          measurement.name === "kaji.subscriber.overflow" &&
          measurement.labels.stage === "overflow",
      ),
    ).toHaveLength(1);
  });

  it("keeps correlation IDs in trace attributes and excludes prompt payloads", async () => {
    const spans: Array<{ name: string; attributes: Record<string, unknown> }> = [];
    const trace: TraceSink = {
      startSpan(name, attributes = {}) {
        const span = { name, attributes: { ...attributes } };
        spans.push(span);
        return {
          setAttribute(key, value) {
            span.attributes[key] = value;
          },
          recordError() {},
          end() {},
        };
      },
    };
    const runtime = new AgentBuilder()
      .provider(new MockProvider({ reply: "done" }))
      .traceSink(trace)
      .build();
    await runtime.turn("prompt-secret", {
      sessionId: "session-id",
      context: {
        principalId: "principal-id",
        requestId: "request-id",
        traceId: "trace-id",
      },
    });

    expect(JSON.stringify(spans)).toContain("request-id");
    expect(JSON.stringify(spans)).toContain("trace-id");
    expect(JSON.stringify(spans)).not.toContain("prompt-secret");
  });
});
