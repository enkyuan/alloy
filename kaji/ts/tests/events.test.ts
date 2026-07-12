import type * as z from "zod";
import { describe, expect, expectTypeOf, it } from "vitest";

import { AgentTurnFailed, KajiEvent, EventType } from "@/index";
import * as eventErrors from "@/events/errors";
import * as eventSchemas from "@/events/schemas";

function snapshotNewEvent(input: unknown): unknown {
  const snapshot = (
    eventSchemas as typeof eventSchemas & {
      snapshotNewEvent?: (value: unknown) => unknown;
    }
  ).snapshotNewEvent;
  expect(snapshot).toBeTypeOf("function");
  return snapshot!(input);
}

function eventWithDurableSubject(subject: string, value: unknown): unknown {
  const base = { id: `event-${subject}`, session_id: "session", timestamp: 1 };
  let event;
  switch (subject) {
    case "tool_result":
      event = KajiEvent.parse({
        ...base,
        type: EventType.TOOL_CALL_COMPLETED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "call",
        result: {},
      });
      (event as { result: unknown }).result = value;
      return event;
    case "workflow_result":
      event = KajiEvent.parse({
        ...base,
        type: EventType.WORKFLOW_COMPLETED,
        workflow_name: "workflow",
        result: {},
      });
      (event as { result: unknown }).result = value;
      return event;
    case "event_metadata":
      event = KajiEvent.parse({ ...base, type: EventType.USER_MESSAGE, content: "hello" });
      (event as { metadata: unknown }).metadata = { value };
      return event;
    case "memory_document":
      event = KajiEvent.parse({
        ...base,
        type: EventType.MEMORY_RETRIEVAL_COMPLETED,
        query: "query",
        documents: [{}],
      });
      (event as { documents: Record<string, unknown>[] }).documents[0]!.value = value;
      return event;
    case "pending_tool_call":
      event = KajiEvent.parse({
        ...base,
        type: EventType.AGENT_TURN_EXHAUSTED,
        max_iterations: 1,
        pending_tool_calls: [{}],
      });
      (event as { pending_tool_calls: Record<string, unknown>[] }).pending_tool_calls[0]!.value =
        value;
      return event;
    case "event":
      event = KajiEvent.parse({ ...base, type: EventType.USER_MESSAGE, content: "hello" });
      (event as { content: unknown }).content = value;
      return event;
    default:
      throw new Error(`Unhandled subject ${subject}`);
  }
}

function eventWithDurableItems(subject: "memory_document" | "pending_tool_call", items: unknown) {
  if (subject === "memory_document") {
    const event = KajiEvent.parse({
      id: "event-memory-items",
      type: EventType.MEMORY_RETRIEVAL_COMPLETED,
      session_id: "session",
      timestamp: 1,
      query: "query",
      documents: [],
    });
    (event as { documents: unknown }).documents = items;
    return event;
  }
  const event = KajiEvent.parse({
    id: "event-pending-items",
    type: EventType.AGENT_TURN_EXHAUSTED,
    session_id: "session",
    timestamp: 1,
    max_iterations: 1,
    pending_tool_calls: [],
  });
  (event as { pending_tool_calls: unknown }).pending_tool_calls = items;
  return event;
}

describe("KajiEvent", () => {
  it.each([
    "tool_result",
    "workflow_result",
    "event_metadata",
    "memory_document",
    "pending_tool_call",
    "event",
  ])("retains typed invalid classification for in-process %s", (subject) => {
    const InvalidDurableValueError = (
      eventErrors as typeof eventErrors & {
        InvalidDurableValueError?: new (...args: never[]) => Error;
      }
    ).InvalidDurableValueError;
    expect(InvalidDurableValueError).toBeTypeOf("function");

    let error: unknown;
    try {
      snapshotNewEvent(eventWithDurableSubject(subject, () => undefined));
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(InvalidDurableValueError!);
    expect(error).toMatchObject({ code: "INVALID_DURABLE_VALUE", subject });
  });

  it.each(["memory_document", "pending_tool_call"] as const)(
    "classifies a sparse %s array by its durable item subject",
    (subject) => {
      expect(() => snapshotNewEvent(eventWithDurableItems(subject, Array(1)))).toThrowError(
        expect.objectContaining({ code: "INVALID_DURABLE_VALUE", subject }),
      );
    },
  );

  it.each(["memory_document", "pending_tool_call"] as const)(
    "classifies an accessor %s item without invoking its getter",
    (subject) => {
      let getterCalls = 0;
      const items: unknown[] = [];
      Object.defineProperty(items, "0", {
        enumerable: true,
        get() {
          getterCalls += 1;
          return { secret: "sk-durable-item-secret" };
        },
      });

      expect(() => snapshotNewEvent(eventWithDurableItems(subject, items))).toThrowError(
        expect.objectContaining({ code: "INVALID_DURABLE_VALUE", subject }),
      );
      expect(getterCalls).toBe(0);
    },
  );

  it.each([
    ["tool_result", 65_536],
    ["workflow_result", 1_048_576],
    ["event_metadata", 1_048_576],
    ["memory_document", 1_048_576],
    ["pending_tool_call", 1_048_576],
    ["event", 1_048_576],
  ] as const)("retains typed size classification for in-process %s", (subject, limit) => {
    const DurableJsonLimitError = (
      eventErrors as typeof eventErrors & {
        DurableJsonLimitError?: new (...args: never[]) => Error;
      }
    ).DurableJsonLimitError;
    expect(DurableJsonLimitError).toBeTypeOf("function");

    let error: unknown;
    try {
      snapshotNewEvent(eventWithDurableSubject(subject, "😀".repeat(Math.floor(limit / 4) + 1)));
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(DurableJsonLimitError!);
    expect(error).toMatchObject({ code: "EVENT_PAYLOAD_TOO_LARGE", subject, maxBytes: limit });
  });

  it("keeps raw-wire durable failures schema incompatible", () => {
    expect(() =>
      eventSchemas.validateNewEvent({
        id: "event",
        version: "1.0",
        timestamp: 1,
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "session",
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "call",
        result: () => undefined,
        metadata: {},
      }),
    ).toThrowError(expect.objectContaining({ code: "EVENT_SCHEMA_INCOMPATIBLE", path: "/result" }));
  });

  it("applies defaults for id, version, timestamp, metadata", () => {
    const event = KajiEvent.parse({
      type: EventType.USER_MESSAGE,
      session_id: "s1",
      content: "hello",
    });

    expect(event.type).toBe(EventType.USER_MESSAGE);
    expect(event.session_id).toBe("s1");
    expect(event.version).toBe("1.0");
    expect(typeof event.id).toBe("string");
    expect(typeof event.timestamp).toBe("number");
    expect(event.metadata).toEqual({});
  });

  it("discriminates on type and keeps variant fields", () => {
    const event = KajiEvent.parse({
      type: EventType.TOOL_CALL_COMPLETED,
      session_id: "s1",
      turn_id: "turn-1",
      tool_name: "get_weather",
      tool_call_id: "c1",
      result: { tempF: 68 },
    });

    expect(event.type).toBe(EventType.TOOL_CALL_COMPLETED);
    if (event.type === EventType.TOOL_CALL_COMPLETED) {
      expect(event.tool_name).toBe("get_weather");
      expect(event.result).toEqual({ tempF: 68 });
    }
  });

  it("rejects unknown fields (strict, matching Pydantic extra=forbid)", () => {
    const parsed = KajiEvent.safeParse({
      type: EventType.USER_MESSAGE,
      session_id: "s1",
      content: "hi",
      bogus: true,
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects an unknown event type", () => {
    const parsed = KajiEvent.safeParse({
      type: "not.a.real.type",
      session_id: "s1",
    });
    expect(parsed.success).toBe(false);
  });

  it("requires bounded public errors and turn identity for terminal failures", () => {
    expectTypeOf<z.input<typeof AgentTurnFailed>["turn_id"]>().toEqualTypeOf<string>();
    expectTypeOf<z.output<typeof AgentTurnFailed>["turn_id"]>().toEqualTypeOf<string>();

    expect(
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        turn_id: "turn-1",
        error: "Agent turn failed",
      }).error,
    ).toBe("Agent turn failed");
    expect(() =>
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        error: "Agent turn failed",
      }),
    ).toThrow();
    expect(() =>
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        turn_id: "turn-1",
        error: "x".repeat(201),
      }),
    ).toThrow();
  });
});
