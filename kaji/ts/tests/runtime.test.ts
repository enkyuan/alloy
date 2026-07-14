import { afterEach, describe, expect, it } from "vitest";
import * as z from "zod";

import { EventBus } from "@/events/bus";
import { InMemoryEventCommitter, SplitEventCommitter } from "@/events/committer";
import { KajiEvent, StoredKajiEvent, type KajiEvent as KajiEventType } from "@/events/schemas";
import { EventType } from "@/events/types";
import { InMemoryEventStore } from "@/events/store";
import type { ModelProviderOptions } from "@/providers/base";
import { MockProvider } from "@/providers/mock";
import type { MetricMeasurement, MetricsSink } from "@/observability";
import { CancellationError, CancellationToken } from "@/runtime/cancellation";
import { ContextIntegrityError, buildMessages } from "@/runtime/context";
import { AgentRuntime, type AgentStrategy } from "@/runtime/runtime";
import { AgentBuilder } from "@/runtime/builder";
import { ToolPolicy } from "@/tools/policy";
import { clearTools, registerTool, toolSpecFromSchema } from "@/tools/registry";
import { replaySession } from "@/sessions/replay";
import type { Message } from "@/sessions/replay";

afterEach(() => clearTools());

function storedEvents(events: readonly KajiEventType[]) {
  return events.map((event, index) => StoredKajiEvent.parse({ ...event, sequence: index + 1 }));
}

describe("replaySession", () => {
  const SESSION = "test-session";

  it("projects TOOL_CALL_FAILED as a tool error message", () => {
    const events = [
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: SESSION, content: "go" }),
      KajiEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "risky_tool",
        tool_args: {},
        tool_call_id: "call_fail_1",
      }),
      KajiEvent.parse({
        type: EventType.TOOL_CALL_STARTED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "risky_tool",
        tool_call_id: "call_fail_1",
      }),
      KajiEvent.parse({
        type: EventType.TOOL_CALL_FAILED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "risky_tool",
        tool_call_id: "call_fail_1",
        error: "connection refused",
      }),
    ];

    const state = replaySession(storedEvents(events));

    expect(state.messages).toHaveLength(3);
    const assistantMsg = state.messages[1]!;
    expect(assistantMsg).toMatchObject({
      role: "assistant",
      content: "",
      toolCalls: [{ id: "call_fail_1", name: "risky_tool", args: {} }],
    });
    const toolMsg = state.messages[2]!;
    expect(toolMsg.role).toBe("tool");
    expect(toolMsg.name).toBe("risky_tool");
    expect(toolMsg.content).toMatch(/^Error: /);
    expect(toolMsg.content).toContain("connection refused");
    expect(toolMsg.toolCallId).toBe("call_fail_1");
  });

  it("TOOL_CALL_FAILED does not appear when TOOL_CALL_COMPLETED follows", () => {
    // Two separate tool calls: one fails, one succeeds. Both must appear in
    // messages with the correct content so the agent loop sees both outcomes.
    const events = [
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: SESSION, content: "go" }),
      // First call: fails
      KajiEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "bad_tool",
        tool_args: {},
        tool_call_id: "call_bad",
      }),
      KajiEvent.parse({
        type: EventType.TOOL_CALL_FAILED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "bad_tool",
        tool_call_id: "call_bad",
        error: "timeout",
      }),
      // Second call: succeeds
      KajiEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "good_tool",
        tool_args: {},
        tool_call_id: "call_good",
      }),
      KajiEvent.parse({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: SESSION,
        turn_id: "turn-1",
        tool_name: "good_tool",
        tool_call_id: "call_good",
        result: { ok: true },
      }),
    ];

    const state = replaySession(storedEvents(events));

    // user + assistant parent + failed tool + completed tool = provider-safe history.
    expect(state.messages).toHaveLength(4);
    const assistantMsg = state.messages[1]!;
    expect(assistantMsg).toMatchObject({
      role: "assistant",
      content: "",
      toolCalls: [
        { id: "call_bad", name: "bad_tool", args: {} },
        { id: "call_good", name: "good_tool", args: {} },
      ],
    });

    const failedMsg = state.messages.find((m) => m.name === "bad_tool")!;
    expect(failedMsg.role).toBe("tool");
    expect(failedMsg.content).toMatch(/^Error: /);
    expect(failedMsg.toolCallId).toBe("call_bad");

    const successMsg = state.messages.find((m) => m.name === "good_tool")!;
    expect(successMsg.role).toBe("tool");
    expect(successMsg.content).not.toMatch(/^Error: /);
    expect(successMsg.toolCallId).toBe("call_good");
  });
});

describe("CancellationToken", () => {
  it("starts not cancelled, flips on cancel", () => {
    const t = new CancellationToken();
    expect(t.isCancelled).toBe(false);
    t.cancel();
    expect(t.isCancelled).toBe(true);
  });

  it("throwIfCancelled throws after cancel", () => {
    const t = new CancellationToken();
    t.cancel();
    expect(() => t.throwIfCancelled()).toThrow(/cancelled/);
  });
});

describe("buildMessages", () => {
  it("prepends a system message when given a prompt", () => {
    const msgs: Message[] = [{ role: "user", content: "hello" }];
    const r = buildMessages(msgs, "You are helpful.");
    expect(r[0]).toEqual({ role: "system", content: "You are helpful." });
    expect(r[1]?.role).toBe("user");
  });

  it("omits system message when no prompt", () => {
    const r = buildMessages([{ role: "user", content: "hi" }]);
    expect(r).toHaveLength(1);
  });

  it("uses the real toolCallId when present (H3)", () => {
    const r = buildMessages([
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "call_abc", name: "get_weather", args: {} }],
      },
      { role: "tool", content: '{"x":1}', name: "get_weather", toolCallId: "call_abc" },
    ]);
    expect(r[1]).toEqual({
      role: "tool",
      content: '{"x":1}',
      name: "get_weather",
      tool_call_id: "call_abc",
    });
  });

  it("fails closed when a tool result has no originating call id", () => {
    expect(() => buildMessages([{ role: "tool", content: "{}", name: "missing-id" }])).toThrow(
      ContextIntegrityError,
    );
  });
});

describe("AgentRuntime.runTurn", () => {
  function setup() {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
      defaultContext: { principalId: "test" },
    });
    return { store, runtime };
  }

  async function seed(store: InMemoryEventStore, sessionId: string) {
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }));
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "hello",
      }),
    );
  }

  it("emits AgentMessageCompleted with no tools registered", async () => {
    const { store, runtime } = setup();
    const s = "s-no-tools";
    await seed(store, s);
    await runtime.runTurn(s);
    const events = await store.getEvents(s);
    expect(events.some((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)).toBe(true);
  });

  it("attaches streamed usage and cost to completed messages", async () => {
    const store = new InMemoryEventStore();
    const provider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* () {
        yield { delta: "hello", toolCalls: [] };
        yield {
          delta: "",
          toolCalls: [],
          usage: { input: 3, output: 2 },
          costUsd: 0.00001125,
        };
      },
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
    });
    const s = "s-usage";

    await seed(store, s);
    await runtime.runTurn(s);

    const completed = (await store.getEvents(s)).find(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );

    expect(completed).toMatchObject({
      content: "hello",
      tokens: { input: 3, output: 2 },
      cost_usd: 0.00001125,
    });
  });

  it("emits the tool lifecycle then completion for one tool call", async () => {
    const { store, runtime } = setup();
    const s = "s-tool";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() }), "read"),
      async () => ({ tempF: 68 }),
    );
    await runtime.runTurn(s);
    const types = (await store.getEvents(s)).map((e) => e.type);
    expect(types).toContain(EventType.TOOL_CALL_REQUESTED);
    expect(types).toContain(EventType.TOOL_CALL_STARTED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(types).toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(types.indexOf(EventType.TOOL_CALL_REQUESTED)).toBeLessThan(
      types.indexOf(EventType.TOOL_CALL_COMPLETED),
    );
  });

  it("emits exactly one completion for one tool call (C2 regression)", async () => {
    const { store, runtime } = setup();
    const s = "s-two-iter";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() }), "read"),
      async () => ({ tempF: 68 }),
    );
    await runtime.runTurn(s);
    // One reasoning-started per runTurn, and exactly one completion: the
    // tool-only first iteration emits no text completion (no phantom), the
    // second iteration's final text emits one.
    const reasoningStarts = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_REASONING_STARTED,
    );
    expect(reasoningStarts).toHaveLength(2);
    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    expect(completions).toHaveLength(1);
  });

  it("emits ToolCallFailed when a tool throws", async () => {
    const { store, runtime } = setup();
    const s = "s-fail";
    await seed(store, s);
    registerTool(toolSpecFromSchema("bad", "fails", z.object({}), "read"), async () => {
      throw new Error("boom");
    });
    await runtime.runTurn(s);
    expect((await store.getEvents(s)).some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(
      true,
    );
  });

  it("preserves assistant text when a turn streams both text and tool calls", async () => {
    // A provider that, on its FIRST turn, returns text AND a tool call in the
    // same response; on the second turn (after the tool result) returns plain
    // text. The first turn's text must be finalized into an
    // AgentMessageCompleted, not dropped (matches the Python reference).
    const store = new InMemoryEventStore();
    const mixedProvider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* (messages: { role: string }[]) {
        const sawToolResult = messages.some((m) => m.role === "tool");
        if (!sawToolResult) {
          yield {
            delta: "Let me check that for you.",
            toolCalls: [{ id: "c1", name: "get_weather", args: {} }],
          };
        } else {
          yield { delta: "It is 68F and sunny.", toolCalls: [] };
        }
      },
    };
    const runtime = new AgentRuntime({
      provider: mixedProvider,
      store,
      committer: new InMemoryEventCommitter(store),
      defaultContext: { principalId: "test" },
    });
    const s = "s-mixed";
    await seed(store, s);
    registerTool(toolSpecFromSchema("get_weather", "weather", z.object({}), "read"), async () => ({
      tempF: 68,
    }));

    await runtime.runTurn(s);

    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    const contents = completions.map((e) => ("content" in e ? e.content : ""));
    // Both the pre-tool text and the final text must be preserved.
    expect(contents).toContain("Let me check that for you.");
    expect(contents).toContain("It is 68F and sunny.");
  });

  it("rejects cancellation before acquiring the session turn", async () => {
    const { store, runtime } = setup();
    const s = "s-cancel";
    await seed(store, s);
    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.runTurn(s, { cancellationToken: token })).rejects.toBeInstanceOf(
      CancellationError,
    );

    const events = await store.getEvents(s);
    const types = events.map((e) => e.type);
    expect(types).not.toContain(EventType.AGENT_REASONING_STARTED);
    expect(types.filter((type) => type === EventType.CANCELLATION_COMPLETED)).toHaveLength(1);
    expect(types).not.toContain(EventType.AGENT_MESSAGE_COMPLETED);
  });

  it("emits cancellation.completed without completing partial text after mid-stream cancel", async () => {
    const store = new InMemoryEventStore();
    const measurements: MetricMeasurement[] = [];
    const metricsSink: MetricsSink = {
      record(measurement) {
        measurements.push(measurement);
      },
    };
    const provider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* (
        _messages: unknown,
        _tools: unknown,
        options?: ModelProviderOptions,
      ) {
        yield { delta: "partial", toolCalls: [] };
        (options?.cancellationToken as CancellationToken | undefined)?.cancel();
        yield { delta: "after-cancel", toolCalls: [] };
      },
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
      metricsSink,
    });
    const s = "s-mid-stream-cancel";
    await seed(store, s);

    await runtime.runTurn(s, { cancellationToken: new CancellationToken() });

    const events = await store.getEvents(s);
    const types = events.map((e) => e.type);
    const deltas = events
      .filter((e) => e.type === EventType.AGENT_MESSAGE_DELTA)
      .map((e) => ("delta" in e ? e.delta : ""));
    expect(deltas).toEqual(["partial"]);
    expect(types.filter((type) => type === EventType.CANCELLATION_COMPLETED)).toHaveLength(1);
    expect(types).not.toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(types).not.toContain(EventType.AGENT_TURN_FAILED);
    expect(
      measurements.some(
        (measurement) =>
          measurement.name === "kaji.provider.duration_ms" &&
          "status" in measurement.labels &&
          measurement.labels.status === "cancelled",
      ),
    ).toBe(true);
  });

  it("still rejects provider errors when the cancellation token is not cancelled", async () => {
    const store = new InMemoryEventStore();
    const error = new Error("provider broke");
    const provider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* () {
        throw error;
        yield { delta: "", toolCalls: [] };
      },
    };
    const runtime = new AgentRuntime({
      provider,
      store,
      committer: new InMemoryEventCommitter(store),
    });
    const s = "s-provider-error";
    await seed(store, s);

    await expect(runtime.runTurn(s, { cancellationToken: new CancellationToken() })).rejects.toBe(
      error,
    );

    const types = (await store.getEvents(s)).map((e) => e.type);
    expect(types).not.toContain(EventType.CANCELLATION_COMPLETED);
  });

  it("does NOT emit an empty completion on max-iteration exhaustion (C1)", async () => {
    // A provider that ALWAYS requests a tool forces the loop to exhaust
    // MAX_TOOL_ITERATIONS. The runtime must not emit an empty AgentMessageCompleted.
    const store = new InMemoryEventStore();
    const alwaysToolProvider = {
      generate: async () => ({
        content: "",
        toolCalls: [{ id: "x", name: "loop", args: {} }],
      }),
      generateStream: async function* () {
        yield { delta: "", toolCalls: [{ id: "x", name: "loop", args: {} }] };
      },
    };
    const runtime = new AgentRuntime({
      provider: alwaysToolProvider,
      store,
      committer: new InMemoryEventCommitter(store),
      defaultContext: { principalId: "test" },
    });
    const s = "s-exhaust";
    await seed(store, s);
    registerTool(toolSpecFromSchema("loop", "always called", z.object({}), "read"), async () => ({
      ok: true,
    }));

    await runtime.runTurn(s);

    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    // No completion with empty content may be emitted.
    expect(completions.every((e) => "content" in e && e.content !== "")).toBe(true);

    const exhausted = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_TURN_EXHAUSTED,
    );
    expect(exhausted).toHaveLength(1);
    expect(exhausted[0]).toMatchObject({
      max_iterations: 5,
      reason: "max_iterations",
      pending_tool_calls: [{ id: "x", name: "loop", arguments: {} }],
    });
  });
});

describe("AgentRuntime.send", () => {
  afterEach(() => clearTools());

  it("appends a USER_MESSAGE event then produces a completion", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
    });
    const s = "s-send";
    // Seed only session_created — no user message yet.
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    await runtime.send(s, "hello from send");

    const events = await store.getEvents(s);
    const userMsg = events.find((e) => e.type === EventType.USER_MESSAGE);
    expect(userMsg).toBeDefined();
    expect((userMsg as any).content).toBe("hello from send");
    expect(events.some((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)).toBe(true);
  });

  it("publishes the USER_MESSAGE through an explicit split committer", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new SplitEventCommitter(store, bus),
    });
    const s = "s-send-bus";
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    const received: string[] = [];
    const sub = bus.subscribe(s);
    (async () => {
      for await (const e of sub) received.push(e.type);
    })();

    await runtime.send(s, "ping");
    sub.return?.();

    expect(received[0]).toBe(EventType.USER_MESSAGE);
  });

  it("does not append a user message when cancelled before send acquisition", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
    });
    const s = "s-send-cancel";
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.send(s, "hello", { cancellationToken: token })).rejects.toBeInstanceOf(
      CancellationError,
    );

    const types = (await store.getEvents(s)).map((e) => e.type);
    expect(types).not.toContain(EventType.USER_MESSAGE);
    expect(types.filter((type) => type === EventType.CANCELLATION_COMPLETED)).toHaveLength(1);
  });
});

describe("AgentStrategy.maxToolIterations", () => {
  afterEach(() => clearTools());

  it("defaults to the shared beta contract limit of five", async () => {
    const store = new InMemoryEventStore();
    let callCount = 0;
    const runtime = new AgentRuntime({
      provider: {
        async generate() {
          return { content: "", toolCalls: [] };
        },
        async *generateStream() {
          callCount++;
          yield { delta: "", toolCalls: [{ id: `default-${callCount}`, name: "noop", args: {} }] };
        },
      },
      store,
      committer: new InMemoryEventCommitter(store),
      defaultContext: { principalId: "test" },
    });
    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "default-five" }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: "default-five",
        content: "go",
      }),
    );
    registerTool(toolSpecFromSchema("noop", "no-op", z.object({}), "read"), async () => ({}));

    await runtime.runTurn("default-five");

    expect(callCount).toBe(5);
  });

  it("respects a custom maxToolIterations lower than the default", async () => {
    const store = new InMemoryEventStore();
    let callCount = 0;
    const countingProvider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* () {
        callCount++;
        // Always request a tool so the loop never exits early on its own.
        yield { delta: "", toolCalls: [{ id: `c${callCount}`, name: "noop", args: {} }] };
      },
    };
    const strategy: AgentStrategy = { maxToolIterations: 3 };
    const runtime = new AgentRuntime({
      provider: countingProvider,
      store,
      committer: new InMemoryEventCommitter(store),
      strategy,
      defaultContext: { principalId: "test" },
    });
    const s = "s-strategy";
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: s, content: "go" }),
    );
    registerTool(toolSpecFromSchema("noop", "no-op", z.object({}), "read"), async () => ({}));

    await runtime.runTurn(s);

    // Provider was called exactly the configured maxToolIterations times.
    expect(callCount).toBe(3);
  });
});

describe("AgentRuntime policy via ToolPlanner", () => {
  afterEach(() => clearTools());

  async function seed(store: InMemoryEventStore, sessionId: string) {
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }));
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "go",
      }),
    );
  }

  it("rejects denied tools through runTurn", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
      policy: new ToolPolicy({ denied: new Set(["get_weather"]) }),
      defaultContext: { principalId: "test" },
    });
    const s = "s-policy-deny";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() }), "read"),
      async () => ({ tempF: 68 }),
    );

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(true);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_COMPLETED)).toBe(false);
  });

  it("runs approval-required tools when approvalHandler approves", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
      policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
      approvalHandler: {
        async request() {
          return { granted: true as const, code: "approved" as const };
        },
      },
      tools: [
        {
          name: "get_weather",
          description: "weather",
          parameters: {},
          risk: "destructive",
        },
      ],
      toolExecutor: async () => ({ tempF: 68 }),
      defaultContext: { principalId: "test" },
    });
    const s = "s-policy-approve";
    await seed(store, s);

    await runtime.runTurn(s);

    const types = (await store.getEvents(s)).map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
  });

  it("runs approval-required tools when a typed approval handler approves", async () => {
    const store = new InMemoryEventStore();
    const runtime = new AgentRuntime({
      provider: new MockProvider(),
      store,
      committer: new InMemoryEventCommitter(store),
      policy: new ToolPolicy({ requireApprovalFor: new Set(["destructive"]) }),
      approvalHandler: {
        async request() {
          return { granted: true, code: "approved" as const };
        },
      },
      tools: [
        {
          name: "get_weather",
          description: "weather",
          parameters: {},
          risk: "destructive",
        },
      ],
      toolExecutor: async () => ({ tempF: 68 }),
      defaultContext: { principalId: "test" },
    });
    const s = "s-policy-typed-approve";
    await seed(store, s);

    await runtime.runTurn(s);

    const types = (await store.getEvents(s)).map((e) => e.type);
    expect(types).toContain(EventType.TOOL_APPROVAL_APPROVED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
  });
});

describe("AgentBuilder policy", () => {
  it("enforces deny policy through builder-created runtime", async () => {
    const store = new InMemoryEventStore();
    const sessionId = "s-builder-deny";

    class WeatherIntegration {
      register(registry: import("@/tools/registry").ToolRegistry): void {
        registry.register(
          toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() }), "read"),
          async () => ({ tempF: 68 }),
        );
      }
    }

    const runtime = new AgentBuilder()
      .provider(new MockProvider())
      .integration(new WeatherIntegration())
      .defaultContext({ principalId: "test" })
      .policy(new ToolPolicy({ denied: new Set(["get_weather"]) }))
      .build({ store });

    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }));
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "go",
      }),
    );
    await runtime.runTurn(sessionId);

    const events = await store.getEvents(sessionId);
    expect(events.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });
});

describe("AgentRuntime cancellationToken forwarded to provider", () => {
  afterEach(() => clearTools());

  it("passes the cancellationToken to generateStream options", async () => {
    const store = new InMemoryEventStore();
    const s = "s-cancel-forward";

    let receivedToken: { isCancelled: boolean } | undefined;

    const tokenCapturingProvider = {
      generate: async () => ({ content: "", toolCalls: [] }),
      generateStream: async function* (
        _messages: unknown,
        _tools: unknown,
        options?: { cancellationToken?: { isCancelled: boolean } },
      ) {
        receivedToken = options?.cancellationToken;
        yield { delta: "done", toolCalls: [] };
      },
    };

    const runtime = new AgentRuntime({
      provider: tokenCapturingProvider,
      store,
      committer: new InMemoryEventCommitter(store),
    });
    await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));
    await store.append(
      KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: s, content: "hi" }),
    );

    const token = new CancellationToken();
    await runtime.runTurn(s, { cancellationToken: token });

    expect(receivedToken).toBeDefined();
    expect(typeof receivedToken?.isCancelled).toBe("boolean");
  });
});
