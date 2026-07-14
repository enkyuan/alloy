import { describe, expect, it, vi } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import type {
  ModelProvider,
  ModelProviderOptions,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ProviderResponseLimits,
} from "@/providers/base";
import { getProviderResponseDiagnostics } from "@/providers/base";
import { ProviderOutputLimitError } from "@/providers/errors";
import { ProviderResponseBudget } from "@/providers/response-budget";
import { CancellationToken } from "@/runtime/cancellation";
import { DeltaAccumulator, RuntimeStreamAccumulator } from "@/runtime/delta-accumulator";
import { TurnTimeoutError } from "@/runtime/limits";
import { AgentRuntime } from "@/runtime/runtime";
import type { ToolSpec } from "@/tools/registry";

class ScriptedProvider implements ModelProvider {
  responseLimits: Readonly<ProviderResponseLimits> | undefined;

  constructor(
    private readonly chunks: readonly ModelResponseChunk[],
    private readonly failure?: Error,
  ) {}

  async generate(): Promise<ModelResponse> {
    return { content: "", toolCalls: [] };
  }

  async *generateStream(
    _messages: ProviderMessage[],
    _tools: ToolSpec[],
    options?: ModelProviderOptions,
  ): AsyncGenerator<ModelResponseChunk> {
    this.responseLimits = options?.responseLimits;
    for (const chunk of this.chunks) yield chunk;
    if (this.failure !== undefined) throw this.failure;
  }
}

function build(
  provider: ModelProvider,
  options: Omit<
    ConstructorParameters<typeof AgentRuntime>[0],
    "provider" | "store" | "committer" | "bus"
  > = {},
) {
  const store = new InMemoryEventStore();
  return {
    store,
    runtime: new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      ...options,
    }),
  };
}

describe("DeltaAccumulator", () => {
  it("rejects thresholds that cannot hold one Unicode scalar", () => {
    expect(() => new DeltaAccumulator(3)).toThrow(/at least four bytes/);
  });

  it("batches 10k fragments without splitting Unicode scalars", () => {
    const accumulator = new DeltaAccumulator(4_096);
    const emitted: string[] = [];
    for (let index = 0; index < 10_000; index += 1) {
      emitted.push(...accumulator.push("x"));
    }
    emitted.push(...accumulator.push("\ud83d"));
    emitted.push(...accumulator.push("\ude00"));
    const residual = accumulator.flush();
    if (residual !== undefined) emitted.push(residual);

    expect(emitted.join("")).toBe(`${"x".repeat(10_000)}😀`);
    expect(emitted.every((delta) => new TextEncoder().encode(delta).byteLength <= 4_096)).toBe(
      true,
    );
    expect(accumulator.totalBytes).toBe(10_004);
    expect(accumulator.diagnostics).toEqual({
      inputFragments: 10_002,
      outputChunks: emitted.length,
      joinOperations: emitted.length,
    });
  });

  it("rejects a dangling surrogate only at the final boundary", () => {
    const accumulator = new DeltaAccumulator();
    expect(accumulator.push("ok\ud83d")).toEqual([]);
    expect(() => accumulator.flush()).toThrow(/unpaired Unicode surrogate/);
  });

  it("uses no latency timers and ignores empty fragments", () => {
    const timer = vi.spyOn(globalThis, "setTimeout");
    const accumulator = new DeltaAccumulator();
    expect(accumulator.push("")).toEqual([]);
    expect(accumulator.flush()).toBeUndefined();
    expect(accumulator.diagnostics).toEqual({
      inputFragments: 0,
      outputChunks: 0,
      joinOperations: 0,
    });
    expect(timer).not.toHaveBeenCalled();
    timer.mockRestore();
  });
});

describe("ProviderResponseBudget", () => {
  it("preflights a normalized chunk atomically and shares its total budget", () => {
    const response = new RuntimeStreamAccumulator({
      textMaxBytes: 8,
      toolArgumentsMaxBytes: 8,
      responseMaxBytes: 7,
      toolCallsMax: 1,
    });
    response.accept({ delta: "abc", toolCalls: [] });

    expect(() =>
      response.accept({ delta: "d", toolCalls: [{ id: "i", name: "n", args: {} }] }),
    ).toThrowError(
      expect.objectContaining({
        code: "PROVIDER_OUTPUT_LIMIT",
        dimension: "total_response",
        limit: 7,
      }),
    );
    expect(response.content()).toBe("abc");
    expect(response.toolCalls).toEqual([]);
  });

  it("counts split Unicode scalars once across raw fragments", () => {
    const budget = new ProviderResponseBudget({
      textMaxBytes: 4,
      toolArgumentsMaxBytes: 8,
      responseMaxBytes: 4,
      toolCallsMax: 1,
    });
    budget.acceptRaw({ text: "\ud83d" });
    budget.acceptRaw({ text: "\ude00" });
    budget.finish();
    expect(budget.diagnostics).toMatchObject({ textBytes: 4, totalResponseBytes: 4 });
  });
});

describe("AgentRuntime provider response boundary", () => {
  it("threads immutable limits and coalesces exact completion text", async () => {
    const provider = new ScriptedProvider(
      Array.from({ length: 10_000 }, () => ({ delta: "x", toolCalls: [] })),
    );
    const { runtime } = build(provider);

    const result = await runtime.turn("hello");

    expect(result.text).toBe("x".repeat(10_000));
    expect(provider.responseLimits).toEqual({
      textMaxBytes: 262_144,
      toolArgumentsMaxBytes: 65_536,
      responseMaxBytes: 524_288,
      toolCallsMax: 64,
    });
    expect(Object.isFrozen(provider.responseLimits)).toBe(true);
    const deltas = result.events
      .filter((event) => event.type === EventType.AGENT_MESSAGE_DELTA)
      .map((event) => event.delta);
    const completed = result.events.find(
      (event) => event.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    expect(deltas.join("")).toBe(completed?.content);
    expect(deltas).toHaveLength(3);
    expect(runtime.streamDiagnostics(result.sessionId)).toEqual({
      inputFragments: 10_000,
      durableDeltaEvents: 3,
      deltaJoinOperations: 3,
      responseJoinOperations: 1,
      textBytes: 10_000,
      totalResponseBytes: 10_000,
      toolCalls: 0,
      rawFragments: 0,
      toolArgumentJoinOperations: 0,
    });
  });

  it("flushes a bounded prefix before a typed terminal and emits no completion", async () => {
    const provider = new ScriptedProvider([
      { delta: "abcd", toolCalls: [] },
      { delta: "é", toolCalls: [] },
    ]);
    const { runtime, store } = build(provider, {
      turnExecutionLimits: {
        providerTextMaxBytes: 5,
        providerResponseMaxBytes: 16,
      },
    } as never);

    await expect(runtime.turn("hello", { sessionId: "limited" })).rejects.toMatchObject({
      code: "PROVIDER_OUTPUT_LIMIT",
      dimension: "text",
      limit: 5,
    });
    const events = await store.getEvents("limited");
    const types = events.map((event) => event.type);
    expect(types).not.toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(types.indexOf(EventType.AGENT_MESSAGE_DELTA)).toBeLessThan(
      types.indexOf(EventType.AGENT_TURN_FAILED),
    );
    expect(events.find((event) => event.type === EventType.AGENT_MESSAGE_DELTA)).toMatchObject({
      delta: "abcd",
    });
    expect(events.find((event) => event.type === EventType.AGENT_TURN_FAILED)).toMatchObject({
      error: "Provider output exceeded text limit of 5 bytes",
      error_code: "PROVIDER_OUTPUT_LIMIT",
      phase: "provider_stream",
      retryable: false,
      outcome: "unknown",
    });
  });

  it("flushes residual text before an ordinary provider failure", async () => {
    const provider = new ScriptedProvider(
      [{ delta: "partial", toolCalls: [] }],
      new Error("provider boom"),
    );
    const { runtime, store } = build(provider);

    await expect(runtime.turn("hello", { sessionId: "failed" })).rejects.toThrow("provider boom");
    const events = await store.getEvents("failed");
    const types = events.map((event) => event.type);
    expect(types.indexOf(EventType.AGENT_MESSAGE_DELTA)).toBeLessThan(
      types.indexOf(EventType.AGENT_TURN_FAILED),
    );
    expect(types).not.toContain(EventType.AGENT_MESSAGE_COMPLETED);
  });

  it("flushes residual text before timeout and cancellation terminals", async () => {
    const timedOut = build(
      new ScriptedProvider(
        [{ delta: "timed", toolCalls: [] }],
        new TurnTimeoutError("provider_stream", false, "unknown"),
      ),
    );
    await expect(timedOut.runtime.turn("hello", { sessionId: "timed-out" })).rejects.toBeInstanceOf(
      TurnTimeoutError,
    );
    const timeoutTypes = (await timedOut.store.getEvents("timed-out")).map((event) => event.type);
    expect(timeoutTypes.indexOf(EventType.AGENT_MESSAGE_DELTA)).toBeLessThan(
      timeoutTypes.indexOf(EventType.AGENT_TURN_FAILED),
    );

    const token = new CancellationToken();
    class CancellingProvider extends ScriptedProvider {
      override async *generateStream(): AsyncGenerator<ModelResponseChunk> {
        yield { delta: "cancelled", toolCalls: [] };
        token.cancel();
        token.throwIfCancelled();
      }
    }
    const cancelled = build(new CancellingProvider([]));
    await expect(
      cancelled.runtime.turn("hello", {
        sessionId: "cancelled",
        cancellationToken: token,
      }),
    ).resolves.toMatchObject({ text: "" });
    const cancellationTypes = (await cancelled.store.getEvents("cancelled")).map(
      (event) => event.type,
    );
    expect(cancellationTypes.indexOf(EventType.AGENT_MESSAGE_DELTA)).toBeLessThan(
      cancellationTypes.indexOf(EventType.CANCELLATION_COMPLETED),
    );
  });

  it("accepts exactly 256 KiB of multibyte text and rejects one additional byte", async () => {
    const exactText = "😀".repeat(65_536);
    const exact = build(new ScriptedProvider([{ delta: exactText, toolCalls: [] }]), {
      turnExecutionLimits: {
        providerTextMaxBytes: 262_144,
        providerResponseMaxBytes: 524_288,
      },
    });
    await expect(exact.runtime.turn("hello")).resolves.toMatchObject({ text: exactText });

    const over = build(new ScriptedProvider([{ delta: `${exactText}a`, toolCalls: [] }]), {
      turnExecutionLimits: {
        providerTextMaxBytes: 262_144,
        providerResponseMaxBytes: 524_288,
      },
    });
    await expect(over.runtime.turn("hello")).rejects.toMatchObject({
      code: "PROVIDER_OUTPUT_LIMIT",
      dimension: "text",
      limit: 262_144,
    });
  });

  it("accepts exactly 512 KiB shared across text and arguments and rejects +1", async () => {
    const overhead = new TextEncoder().encode('{"value":""}').byteLength;
    const args = { value: "é".repeat((65_536 - overhead) / 2) };
    const calls = ["a", "b", "c", "d"].map((id) => ({ id, name: "n", args }));
    const exactText = "x".repeat(262_136);
    const options = { strategy: { allowToolCalls: false } } as const;
    const exact = build(new ScriptedProvider([{ delta: exactText, toolCalls: calls }]), options);
    await expect(exact.runtime.turn("hello")).resolves.toBeDefined();

    const over = build(
      new ScriptedProvider([{ delta: `${exactText}x`, toolCalls: calls }]),
      options,
    );
    await expect(over.runtime.turn("hello")).rejects.toMatchObject({
      code: "PROVIDER_OUTPUT_LIMIT",
      dimension: "total_response",
      limit: 524_288,
    });
  });

  it("accepts exact canonical tool arguments and rejects one byte over", async () => {
    const overhead = new TextEncoder().encode('{"value":""}').byteLength;
    const exactArgs = { value: "é".repeat((65_536 - overhead) / 2) };
    const exact = build(
      new ScriptedProvider([{ delta: "", toolCalls: [{ id: "i", name: "n", args: exactArgs }] }]),
      { strategy: { allowToolCalls: false } },
    );
    await expect(exact.runtime.turn("hello")).resolves.toBeDefined();

    const over = build(
      new ScriptedProvider([
        {
          delta: "",
          toolCalls: [{ id: "i", name: "n", args: { value: `${exactArgs.value}a` } }],
        },
      ]),
      { strategy: { allowToolCalls: false } },
    );
    await expect(over.runtime.turn("hello")).rejects.toMatchObject({
      code: "PROVIDER_OUTPUT_LIMIT",
      dimension: "tool_arguments",
      limit: 65_536,
    });
  });

  it("accepts 64 calls and rejects 65 before tool execution", async () => {
    const calls = Array.from({ length: 64 }, (_, index) => ({
      id: `call-${index}`,
      name: "lookup",
      args: {},
    }));
    const allowed = build(new ScriptedProvider([{ delta: "", toolCalls: calls }]), {
      strategy: { allowToolCalls: false },
    } as never);
    await expect(allowed.runtime.turn("hello")).resolves.toBeDefined();

    const execute = vi.fn();
    const rejected = build(
      new ScriptedProvider([
        {
          delta: "",
          toolCalls: [...calls, { id: "call-65", name: "lookup", args: {} }],
        },
      ]),
      { toolExecutor: execute } as never,
    );
    await expect(rejected.runtime.turn("hello", { sessionId: "calls" })).rejects.toBeInstanceOf(
      ProviderOutputLimitError,
    );
    expect(execute).not.toHaveBeenCalled();
    expect((await rejected.store.getEvents("calls")).map((event) => event.type)).not.toContain(
      EventType.TOOL_CALL_REQUESTED,
    );
  });

  it("detaches and freezes normalized tool calls synchronously", () => {
    const call = { id: "call", name: "lookup", args: { value: "before" } };
    const response = new RuntimeStreamAccumulator({
      textMaxBytes: 262_144,
      toolArgumentsMaxBytes: 65_536,
      responseMaxBytes: 524_288,
      toolCallsMax: 64,
    });
    response.accept({ delta: "", toolCalls: [call] });
    call.args.value = "after";
    expect(response.toolCalls[0]?.args).toEqual({ value: "before" });
    expect(Object.isFrozen(response.toolCalls[0]?.args)).toBe(true);
  });

  it("does not persist empty provider deltas or an empty completion", async () => {
    const { runtime } = build(
      new ScriptedProvider([
        { delta: "", toolCalls: [] },
        { delta: "", toolCalls: [] },
      ]),
    );
    const result = await runtime.turn("hello");
    expect(result.events.map((event) => event.type)).not.toContain(EventType.AGENT_MESSAGE_DELTA);
    expect(result.events.map((event) => event.type)).not.toContain(
      EventType.AGENT_MESSAGE_COMPLETED,
    );
  });

  it("flushes residual text before requesting and executing a tool", async () => {
    let providerCalls = 0;
    const provider: ModelProvider = {
      async generate() {
        return { content: "", toolCalls: [] };
      },
      async *generateStream() {
        if (providerCalls++ === 0) {
          yield {
            delta: "residual",
            toolCalls: [{ id: "call", name: "lookup", args: {} }],
          };
        } else {
          yield { delta: "done", toolCalls: [] };
        }
      },
    };
    const store = new InMemoryEventStore();
    let typesAtExecution: EventType[] = [];
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      tools: [{ name: "lookup", description: "lookup", parameters: {}, risk: "read" }],
      toolExecutor: async () => {
        typesAtExecution = (await store.getEvents("tool-order")).map((event) => event.type);
        return { ok: true };
      },
      defaultContext: { principalId: "test" },
    });
    await runtime.turn("hello", { sessionId: "tool-order" });

    expect(typesAtExecution.indexOf(EventType.AGENT_MESSAGE_DELTA)).toBeLessThan(
      typesAtExecution.indexOf(EventType.TOOL_CALL_REQUESTED),
    );
  });

  it("retains an immutable per-call adapter diagnostics snapshot", async () => {
    class DiagnosedProvider extends ScriptedProvider {
      override async *generateStream(
        _messages: ProviderMessage[],
        _tools: ToolSpec[],
        options?: ModelProviderOptions,
      ): AsyncGenerator<ModelResponseChunk> {
        yield { delta: "ok", toolCalls: [] };
        getProviderResponseDiagnostics(options)?.record({
          rawFragments: 10_002,
          toolArgumentJoinOperations: 1,
        });
      }
    }
    const { runtime } = build(new DiagnosedProvider([]));
    const result = await runtime.turn("hello");
    expect(runtime.streamDiagnostics(result.sessionId)).toMatchObject({
      rawFragments: 10_002,
      toolArgumentJoinOperations: 1,
    });
    expect(Object.isFrozen(runtime.streamDiagnostics(result.sessionId))).toBe(true);
  });
});
