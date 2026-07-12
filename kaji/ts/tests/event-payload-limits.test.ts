import { describe, expect, it } from "vitest";

import { EventSchemaIncompatibleError } from "@/events/errors";
import * as eventSchemas from "@/events/schemas";
import { canonicalJsonValue } from "@/events/json";
import {
  KajiEvent,
  MAX_DURABLE_TOOL_ARGUMENT_BYTES,
  durableToolArgumentsSize,
} from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";

function snapshotNewEvent(value: unknown): unknown {
  const snapshot = (
    eventSchemas as typeof eventSchemas & {
      snapshotNewEvent?: (input: unknown) => unknown;
    }
  ).snapshotNewEvent;
  expect(snapshot).toBeTypeOf("function");
  return snapshot!(value);
}

function jsonValueOfSize(size: number, multibyte: boolean): Record<string, string> {
  const emptySize = new TextEncoder().encode('{"value":""}').byteLength;
  const remaining = size - emptySize;
  return {
    value: multibyte
      ? "😀".repeat(Math.floor(remaining / 4)) + "x".repeat(remaining % 4)
      : "x".repeat(remaining),
  };
}

it.each([false, true])(
  "bounds durable tool results by exact UTF-8 bytes (multibyte=%s)",
  (multibyte) => {
    const maxBytes = (
      eventSchemas as typeof eventSchemas & {
        MAX_DURABLE_TOOL_RESULT_BYTES?: number;
      }
    ).MAX_DURABLE_TOOL_RESULT_BYTES;
    expect(maxBytes).toBe(65_536);
    const base = {
      id: "tool-result",
      version: "1.0",
      timestamp: 1,
      type: EventType.TOOL_CALL_COMPLETED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      metadata: {},
    };

    expect(() =>
      snapshotNewEvent({ ...base, result: jsonValueOfSize(maxBytes!, multibyte) }),
    ).not.toThrow();
    expect(() =>
      snapshotNewEvent({ ...base, result: jsonValueOfSize(maxBytes! + 1, multibyte) }),
    ).toThrowError(
      expect.objectContaining({
        code: "EVENT_PAYLOAD_TOO_LARGE",
        subject: "tool_result",
        maxBytes,
      }),
    );
  },
);

it.each([false, true])(
  "bounds the whole durable event by exact UTF-8 bytes (multibyte=%s)",
  (multibyte) => {
    const maxBytes = (
      eventSchemas as typeof eventSchemas & {
        MAX_DURABLE_EVENT_BYTES?: number;
      }
    ).MAX_DURABLE_EVENT_BYTES;
    expect(maxBytes).toBe(1_048_576);
    const base = {
      id: "whole-event",
      version: "1.0",
      timestamp: 1,
      type: EventType.USER_MESSAGE,
      session_id: "session",
      content: "",
      metadata: {},
    };
    const baseBytes = new TextEncoder().encode(canonicalJsonValue(base)).byteLength;
    const remaining = maxBytes! - baseBytes;
    const content = multibyte
      ? "😀".repeat(Math.floor(remaining / 4)) + "x".repeat(remaining % 4)
      : "x".repeat(remaining);

    expect(new TextEncoder().encode(canonicalJsonValue({ ...base, content })).byteLength).toBe(
      maxBytes,
    );
    expect(() => snapshotNewEvent({ ...base, content })).not.toThrow();
    expect(() => snapshotNewEvent({ ...base, content: `${content}x` })).toThrowError(
      expect.objectContaining({
        code: "EVENT_PAYLOAD_TOO_LARGE",
        subject: "event",
        maxBytes,
      }),
    );
  },
);

function argumentsOfSize(size: number, marker = "", multibyte = false): Record<string, string> {
  const emptySize = new TextEncoder().encode(JSON.stringify({ value: "" })).byteLength;
  const markerSize = new TextEncoder().encode(marker).byteLength;
  const remaining = size - emptySize - markerSize;
  const value = multibyte
    ? marker + "😀".repeat(Math.floor(remaining / 4)) + "x".repeat(remaining % 4)
    : marker + "x".repeat(remaining);
  return { value };
}

describe.each([
  [EventType.TOOL_CALL_REQUESTED, {}],
  [EventType.TOOL_APPROVAL_REQUESTED, { risk: "write" }],
] as const)("%s durable payload bound", (type, extra) => {
  const base = {
    type,
    session_id: "session",
    turn_id: "turn",
    tool_name: "tool",
    tool_call_id: "call",
    ...extra,
  };

  it.each([
    [MAX_DURABLE_TOOL_ARGUMENT_BYTES - 1, false],
    [MAX_DURABLE_TOOL_ARGUMENT_BYTES, false],
    [MAX_DURABLE_TOOL_ARGUMENT_BYTES - 1, true],
    [MAX_DURABLE_TOOL_ARGUMENT_BYTES, true],
  ])("accepts %i serialized bytes (multibyte=%s)", (size, multibyte) => {
    const event = KajiEvent.parse({ ...base, tool_args: argumentsOfSize(size, "", multibyte) });
    expect("tool_args" in event).toBe(true);
    if (!("tool_args" in event)) throw new Error("tool event lost its arguments");
    expect(new TextEncoder().encode(JSON.stringify(event.tool_args))).toHaveLength(size);
  });

  it.each([false, true])(
    "rejects an oversize payload without echoing its contents (multibyte=%s)",
    (multibyte) => {
      const secret = "sk-release-payload-secret";
      const parsed = KajiEvent.safeParse({
        ...base,
        tool_args: argumentsOfSize(MAX_DURABLE_TOOL_ARGUMENT_BYTES + 1, secret, multibyte),
      });

      expect(parsed.success).toBe(false);
      if (parsed.success) return;
      expect(parsed.error.message).toContain("65536 serialized bytes");
      expect(parsed.error.message).not.toContain(secret);
    },
  );
});

it("uses the shared number policy for boundary decisions", () => {
  const empty = { numbers: [1, -0, 1.25e-7, 4503599627370495.5], value: "" };
  const canonical = '{"numbers":[1,0,1.25e-7,4503599627370495.5],"value":""}';
  expect(durableToolArgumentsSize(empty)).toBe(new TextEncoder().encode(canonical).byteLength);
  const exact = {
    ...empty,
    value: "x".repeat(MAX_DURABLE_TOOL_ARGUMENT_BYTES - canonical.length),
  };
  expect(
    KajiEvent.safeParse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      tool_args: exact,
    }).success,
  ).toBe(true);
  expect(
    KajiEvent.safeParse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      tool_args: { ...exact, value: `${exact.value}x` },
    }).success,
  ).toBe(false);
});

it.each([{ value: undefined }, { value: 1n }, { value: new Date(0) }])(
  "rejects representative non-JSON values without reflection",
  (tool_args) => {
    const result = KajiEvent.safeParse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      tool_args,
    });
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.message).toContain("only JSON values");
  },
);

it("rejects cyclic tool arguments without reflection", () => {
  const tool_args: Record<string, unknown> = { secret: "sk-cyclic-secret" };
  tool_args.cycle = tool_args;
  const result = KajiEvent.safeParse({
    type: EventType.TOOL_CALL_REQUESTED,
    session_id: "session",
    turn_id: "turn",
    tool_name: "tool",
    tool_call_id: "call",
    tool_args,
  });
  expect(result.success).toBe(false);
  if (!result.success) expect(result.error.message).not.toContain("sk-cyclic-secret");
});

it("rejects arrays with hidden named properties", () => {
  const value: unknown[] = [];
  Object.defineProperty(value, "hidden", {
    value: "sk-hidden-array-secret",
    enumerable: false,
  });
  const result = KajiEvent.safeParse({
    type: EventType.TOOL_CALL_REQUESTED,
    session_id: "session",
    turn_id: "turn",
    tool_name: "tool",
    tool_call_id: "call",
    tool_args: { value },
  });
  expect(result.success).toBe(false);
  if (!result.success) expect(result.error.message).not.toContain("sk-hidden-array-secret");
});

it.each(["\ud800", "\udc00"])("rejects an unpaired Unicode surrogate", (value) => {
  const result = KajiEvent.safeParse({
    type: EventType.TOOL_CALL_REQUESTED,
    session_id: "session",
    turn_id: "turn",
    tool_name: "tool",
    tool_call_id: "call",
    tool_args: { value },
  });
  expect(result.success).toBe(false);
  if (!result.success) expect(result.error.message).toContain("only JSON values");
});

it("counts a valid supplementary character by its UTF-8 bytes", () => {
  const arguments_ = { value: "😀" };
  expect(durableToolArgumentsSize(arguments_)).toBe(
    new TextEncoder().encode('{"value":"😀"}').byteLength,
  );
  expect(
    KajiEvent.safeParse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      tool_args: arguments_,
    }).success,
  ).toBe(true);
});

it.each([
  [EventType.TOOL_CALL_REQUESTED, {}],
  [EventType.TOOL_APPROVAL_REQUESTED, { risk: "write" }],
] as const)("revalidates mutated %s arguments at the store boundary", async (type, extra) => {
  const event = KajiEvent.parse({
    type,
    session_id: "session",
    turn_id: "turn",
    tool_name: "tool",
    tool_call_id: "call",
    tool_args: {},
    ...extra,
  });
  if (!("tool_args" in event)) throw new Error("expected a tool argument event");
  (event.tool_args as Record<string, unknown>).secret = "x".repeat(70_000);

  await expect(new InMemoryEventStore().append(event)).rejects.toMatchObject({
    code: "EVENT_SCHEMA_INCOMPATIBLE",
    path: "/tool_args",
  } satisfies Partial<EventSchemaIncompatibleError>);
});
