import { describe, expect, it } from "vitest";

import { KajiEvent, EventType, replaySession } from "@/index";

function ev(input: Record<string, unknown>) {
  return KajiEvent.parse(input);
}

describe("replaySession", () => {
  it("projects a conversation from the event log", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({
        type: EventType.USER_MESSAGE,
        session_id: "s1",
        content: "hi",
        timestamp: 2,
      }),
      ev({
        type: EventType.AGENT_MESSAGE_COMPLETED,
        session_id: "s1",
        content: "hello",
        timestamp: 3,
      }),
    ]);

    expect(state.sessionId).toBe("s1");
    expect(state.isActive).toBe(true);
    expect(state.messages).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ]);
  });

  it("orders by timestamp and flips isActive on close", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CLOSED, session_id: "s1", timestamp: 9 }),
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
    ]);
    expect(state.isActive).toBe(false);
  });

  it("treats a final transcript as a user message and records tool results", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({
        type: EventType.TRANSCRIPT_FINAL,
        session_id: "s1",
        text: "what is the weather",
        timestamp: 2,
      }),
      ev({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "s1",
        tool_name: "get_weather",
        tool_call_id: "c1",
        result: { tempF: 68 },
        timestamp: 3,
      }),
    ]);

    expect(state.messages).toEqual([
      { role: "user", content: "what is the weather" },
      {
        role: "tool",
        name: "get_weather",
        content: '{"tempF":68}',
        toolCallId: "c1",
      },
    ]);
  });

  it("preserves the real tool_call_id on tool messages (H3)", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "s1",
        tool_name: "do_thing",
        tool_call_id: "call_abc",
        result: { ok: true },
        timestamp: 2,
      }),
    ]);
    const tool = state.messages.find((m) => m.role === "tool");
    expect(tool?.toolCallId).toBe("call_abc");
  });

  it("attaches requested tool calls to the preceding assistant message", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({
        type: EventType.AGENT_MESSAGE_COMPLETED,
        session_id: "s1",
        content: "I will check.",
        timestamp: 2,
      }),
      ev({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: "s1",
        tool_name: "get_weather",
        tool_args: { city: "Seattle" },
        tool_call_id: "call_weather",
        timestamp: 3,
      }),
    ]);

    expect(state.messages).toEqual([
      {
        role: "assistant",
        content: "I will check.",
        toolCalls: [
          {
            id: "call_weather",
            name: "get_weather",
            args: { city: "Seattle" },
          },
        ],
      },
    ]);
  });

  it("synthesizes an assistant message for tool-only model output", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: "s1",
        tool_name: "echo_probe",
        tool_args: { value: "ping" },
        tool_call_id: "call_echo",
        timestamp: 2,
      }),
      ev({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "s1",
        tool_name: "echo_probe",
        tool_call_id: "call_echo",
        result: { value: "ping" },
        timestamp: 3,
      }),
    ]);

    expect(state.messages).toEqual([
      {
        role: "assistant",
        content: "",
        toolCalls: [{ id: "call_echo", name: "echo_probe", args: { value: "ping" } }],
      },
      {
        role: "tool",
        name: "echo_probe",
        content: '{"value":"ping"}',
        toolCallId: "call_echo",
      },
    ]);
  });

  it("throws on an empty log", () => {
    expect(() => replaySession([])).toThrow(/empty event log/);
  });
});
