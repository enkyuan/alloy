import { describe, expect, it } from "vitest";

import { EventSchemaIncompatibleError } from "@/events/errors";
import {
  KajiEvent,
  MAX_DURABLE_TOOL_ARGUMENT_BYTES,
  durableToolArgumentsSize,
} from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";

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
