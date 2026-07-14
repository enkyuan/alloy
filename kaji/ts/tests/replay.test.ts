import { describe, expect, it } from "vitest";

import { StoredKajiEvent, EventType, replaySession } from "@/index";
import { EventSchemaIncompatibleError } from "@/events/errors";

function ev(input: Record<string, unknown>) {
  const type = input.type;
  return StoredKajiEvent.parse({
    ...input,
    sequence: input.timestamp,
    ...(typeof type === "string" && type.startsWith("tool.call.") && input.turn_id === undefined
      ? { turn_id: "test-turn" }
      : {}),
  });
}

function invalidToolResultEvent(result: unknown) {
  const event = ev({
    type: EventType.TOOL_CALL_COMPLETED,
    session_id: "s-json-invalid",
    tool_name: "fixture",
    tool_call_id: "call-json-invalid",
    result: {},
    timestamp: 1,
  });
  return { ...event, result } as typeof event;
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

  it("replays stored order and flips isActive on close", () => {
    const state = replaySession([
      ev({ type: EventType.SESSION_CREATED, session_id: "s1", timestamp: 1 }),
      ev({ type: EventType.SESSION_CLOSED, session_id: "s1", timestamp: 9 }),
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

  it.each([
    [true, "true"],
    [null, "null"],
    [7.5, "7.5"],
    [1.0, "1"],
    [-0.0, "0"],
    [1e-6, "0.000001"],
    [1.25e-7, "1.25e-7"],
    [4503599627370495.5, "4503599627370495.5"],
    [Number.MAX_SAFE_INTEGER, "9007199254740991"],
    [Number.MIN_SAFE_INTEGER, "-9007199254740991"],
    ["café", '"café"'],
    [[1, false, null], "[1,false,null]"],
    [{ nested: { ok: true } }, '{"nested":{"ok":true}}'],
    [{ 2: "two", 10: "ten" }, '{"10":"ten","2":"two"}'],
    [{ "\ue000": "bmp", "\u{10000}": "astral" }, '{"\u{10000}":"astral","\ue000":"bmp"}'],
  ])("renders JSON tool result %j canonically", (result, expected) => {
    const state = replaySession([
      ev({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "s-json",
        tool_name: "fixture",
        tool_call_id: "call-json",
        result,
        timestamp: 1,
      }),
    ]);

    expect(state.messages.at(-1)?.content).toBe(expected);
  });

  it.each([
    ["Date", new Date(0)],
    ["Map", new Map([["visible", true]])],
  ])("rejects non-plain %s tool results", (_label, result) => {
    try {
      replaySession([invalidToolResultEvent(result)]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/result");
    }
  });

  it("rejects symbol-keyed tool-result objects", () => {
    const result = { visible: true, [Symbol("hidden")]: false };

    try {
      replaySession([invalidToolResultEvent(result)]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/result");
    }
  });

  it("rejects an exact integer represented outside the Number domain", () => {
    try {
      replaySession([invalidToolResultEvent(9007199254740993n)]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/result");
    }
  });

  it.each([2 ** 53, -(2 ** 53)])("rejects unsafe integral number %s", (result) => {
    try {
      replaySession([invalidToolResultEvent(result)]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/result");
    }
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
