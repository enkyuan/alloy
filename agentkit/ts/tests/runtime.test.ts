import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import { EventBus } from "../src/events/bus";
import { AgentKitEvent } from "../src/events/schemas";
import { EventType } from "../src/events/types";
import { InMemoryEventStore } from "../src/events/store";
import { MockProvider } from "../src/providers/mock";
import { CancellationToken } from "../src/runtime/cancellation";
import { buildMessages } from "../src/runtime/context";
import { AgentRuntime, type AgentStrategy } from "../src/runtime/runtime";
import { clearTools, registerTool, toolSpecFromSchema } from "../src/tools/registry";
import { replaySession } from "../src/sessions/replay";
import type { Message } from "../src/sessions/replay";

afterEach(() => clearTools());

describe("replaySession", () => {
  const SESSION = "test-session";

  it("projects TOOL_CALL_FAILED as a tool error message", () => {
    const events = [
      AgentKitEvent.parse({ type: EventType.USER_MESSAGE, session_id: SESSION, content: "go" }),
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        tool_name: "risky_tool",
        tool_args: {},
        tool_call_id: "call_fail_1",
      }),
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_STARTED,
        session_id: SESSION,
        tool_name: "risky_tool",
        tool_call_id: "call_fail_1",
      }),
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_FAILED,
        session_id: SESSION,
        tool_name: "risky_tool",
        tool_call_id: "call_fail_1",
        error: "connection refused",
      }),
    ];

    const state = replaySession(events);

    expect(state.messages).toHaveLength(2);
    const toolMsg = state.messages[1]!;
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
      AgentKitEvent.parse({ type: EventType.USER_MESSAGE, session_id: SESSION, content: "go" }),
      // First call: fails
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        tool_name: "bad_tool",
        tool_args: {},
        tool_call_id: "call_bad",
      }),
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_FAILED,
        session_id: SESSION,
        tool_name: "bad_tool",
        tool_call_id: "call_bad",
        error: "timeout",
      }),
      // Second call: succeeds
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: SESSION,
        tool_name: "good_tool",
        tool_args: {},
        tool_call_id: "call_good",
      }),
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: SESSION,
        tool_name: "good_tool",
        tool_call_id: "call_good",
        result: { ok: true },
      }),
    ];

    const state = replaySession(events);

    // user + failed tool + completed tool = 3 messages
    expect(state.messages).toHaveLength(3);

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
      { role: "tool", content: '{"x":1}', name: "get_weather", toolCallId: "call_abc" },
    ]);
    expect(r[0]).toEqual({
      role: "tool",
      content: '{"x":1}',
      name: "get_weather",
      tool_call_id: "call_abc",
    });
  });

  it("falls back to name only when no toolCallId is present", () => {
    const r = buildMessages([{ role: "tool", content: "{}", name: "legacy" }]);
    expect(r[0]?.tool_call_id).toBe("legacy");
  });
});

describe("AgentRuntime.runTurn", () => {
  function setup() {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });
    return { store, bus, runtime };
  }

  async function seed(store: InMemoryEventStore, sessionId: string) {
    await store.append(
      AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }),
    );
    await store.append(
      AgentKitEvent.parse({
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

  it("emits the tool lifecycle then completion for one tool call", async () => {
    const { store, runtime } = setup();
    const s = "s-tool";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() })),
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
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() })),
      async () => ({ tempF: 68 }),
    );
    await runtime.runTurn(s);
    // One reasoning-started per runTurn, and exactly one completion: the
    // tool-only first iteration emits no text completion (no phantom), the
    // second iteration's final text emits one.
    const reasoningStarts = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_REASONING_STARTED,
    );
    expect(reasoningStarts).toHaveLength(1);
    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    expect(completions).toHaveLength(1);
  });

  it("emits ToolCallFailed when a tool throws", async () => {
    const { store, runtime } = setup();
    const s = "s-fail";
    await seed(store, s);
    registerTool(toolSpecFromSchema("bad", "fails", z.object({})), async () => {
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
    const bus = new EventBus();
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
    const runtime = new AgentRuntime({ provider: mixedProvider, store, bus });
    const s = "s-mixed";
    await seed(store, s);
    registerTool(toolSpecFromSchema("get_weather", "weather", z.object({})), async () => ({
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

  it("rejects when cancelled before the loop", async () => {
    const { store, runtime } = setup();
    const s = "s-cancel";
    await seed(store, s);
    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.runTurn(s, { cancellationToken: token })).rejects.toThrow(/cancelled/);
  });

  it("does NOT emit an empty completion on max-iteration exhaustion (C1)", async () => {
    // A provider that ALWAYS requests a tool forces the loop to exhaust
    // MAX_TOOL_ITERATIONS. The runtime must not emit an empty AgentMessageCompleted.
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const alwaysToolProvider = {
      generate: async () => ({
        content: "",
        toolCalls: [{ id: "x", name: "loop", args: {} }],
      }),
      generateStream: async function* () {
        yield { delta: "", toolCalls: [{ id: "x", name: "loop", args: {} }] };
      },
    };
    const runtime = new AgentRuntime({ provider: alwaysToolProvider, store, bus });
    const s = "s-exhaust";
    await seed(store, s);
    registerTool(toolSpecFromSchema("loop", "always called", z.object({})), async () => ({
      ok: true,
    }));

    await runtime.runTurn(s);

    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    // No completion with empty content may be emitted.
    expect(completions.every((e) => "content" in e && e.content !== "")).toBe(true);
  });
});

describe("AgentRuntime.send", () => {
  afterEach(() => clearTools());

  it("appends a USER_MESSAGE event then produces a completion", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });
    const s = "s-send";
    // Seed only session_created — no user message yet.
    await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    await runtime.send(s, "hello from send");

    const events = await store.getEvents(s);
    const userMsg = events.find((e) => e.type === EventType.USER_MESSAGE);
    expect(userMsg).toBeDefined();
    expect((userMsg as any).content).toBe("hello from send");
    expect(events.some((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)).toBe(true);
  });

  it("publishes the USER_MESSAGE to the bus before running the turn", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });
    const s = "s-send-bus";
    await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    const received: string[] = [];
    const sub = bus.subscribe(s);
    (async () => {
      for await (const e of sub) received.push(e.type);
    })();

    await runtime.send(s, "ping");
    sub.return?.();

    expect(received[0]).toBe(EventType.USER_MESSAGE);
  });

  it("forwards cancellationToken to runTurn", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });
    const s = "s-send-cancel";
    await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));

    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.send(s, "hello", { cancellationToken: token })).rejects.toThrow(
      /cancelled/,
    );
  });
});

describe("AgentStrategy.maxToolIterations", () => {
  afterEach(() => clearTools());

  it("respects a custom maxToolIterations lower than the default", async () => {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
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
    const runtime = new AgentRuntime({ provider: countingProvider, store, bus, strategy });
    const s = "s-strategy";
    await store.append(AgentKitEvent.parse({ type: EventType.SESSION_CREATED, session_id: s }));
    await store.append(
      AgentKitEvent.parse({ type: EventType.USER_MESSAGE, session_id: s, content: "go" }),
    );
    registerTool(toolSpecFromSchema("noop", "no-op", z.object({})), async () => ({}));

    await runtime.runTurn(s);

    // Provider was called exactly maxToolIterations times (not the default 10).
    expect(callCount).toBe(3);
  });
});
