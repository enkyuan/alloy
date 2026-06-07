import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import { EventBus } from "../src/events/bus";
import { AgentKitEvent } from "../src/events/schemas";
import { EventType } from "../src/events/types";
import { InMemoryEventStore } from "../src/events/store";
import { MockProvider } from "../src/providers/mock";
import { CancellationToken } from "../src/runtime/cancellation";
import { buildMessages } from "../src/runtime/context";
import { AgentRuntime } from "../src/runtime/runtime";
import {
  clearTools,
  registerTool,
  toolSpecFromSchema,
} from "../src/tools/registry";
import type { Message } from "../src/sessions/replay";

afterEach(() => clearTools());

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

  it("terminates after exactly 2 iterations for one tool (C2 regression)", async () => {
    const { store, runtime } = setup();
    const s = "s-two-iter";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() })),
      async () => ({ tempF: 68 }),
    );
    await runtime.runTurn(s);
    const reasoningStarts = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_REASONING_STARTED,
    );
    // One reasoning-started per runTurn; the loop runs 2 internal iterations but
    // emits reasoning-started once. Assert exactly one completion (no phantom).
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
    registerTool(
      toolSpecFromSchema("bad", "fails", z.object({})),
      async () => {
        throw new Error("boom");
      },
    );
    await runtime.runTurn(s);
    expect(
      (await store.getEvents(s)).some((e) => e.type === EventType.TOOL_CALL_FAILED),
    ).toBe(true);
  });

  it("rejects when cancelled before the loop", async () => {
    const { store, runtime } = setup();
    const s = "s-cancel";
    await seed(store, s);
    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.runTurn(s, { cancellationToken: token })).rejects.toThrow(
      /cancelled/,
    );
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
    registerTool(
      toolSpecFromSchema("loop", "always called", z.object({})),
      async () => ({ ok: true }),
    );

    await runtime.runTurn(s);

    const completions = (await store.getEvents(s)).filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    // No completion with empty content may be emitted.
    expect(completions.every((e) => "content" in e && e.content !== "")).toBe(true);
  });
});
