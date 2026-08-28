import { describe, expect, it } from "vitest";

import * as eventJson from "@/events/json";
import { DurableJsonLimitError, InvalidDurableValueError } from "@/events/errors";

const durableJsonSnapshot = (value: unknown, subject: string, maxBytes: number): unknown => {
  const snapshot = (
    eventJson as typeof eventJson & {
      durableJsonSnapshot?: (input: unknown, durableSubject: string, limit: number) => unknown;
    }
  ).durableJsonSnapshot;
  expect(snapshot).toBeTypeOf("function");
  return snapshot!(value, subject, maxBytes);
};

describe("event JSON helpers", () => {
  it("rejects cycles in cloning and canonical comparison", () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;

    expect(() => eventJson.cloneAndFreezeJson(cyclic)).toThrow(/acyclic/i);
    expect(() => eventJson.structurallyEqualJson(cyclic, cyclic)).toThrow(/acyclic/i);
  });

  it("preserves an own __proto__ key without changing the clone prototype", () => {
    const input = JSON.parse('{"__proto__":{"polluted":true},"safe":1}') as Record<string, unknown>;

    const clone = eventJson.cloneAndFreezeJson(input);

    expect(Object.getPrototypeOf(clone)).toBe(Object.prototype);
    expect(Object.hasOwn(clone, "__proto__")).toBe(true);
    expect((clone.__proto__ as { readonly polluted: boolean }).polluted).toBe(true);
    expect(({} as { polluted?: boolean }).polluted).toBeUndefined();
  });

  it("detaches, normalizes, and deeply freezes a durable snapshot", () => {
    const source = { nested: [{ value: -0 }], text: "before" };

    const snapshot = durableJsonSnapshot(source, "event", 1_024) as {
      readonly nested: readonly [{ readonly value: number }];
      readonly text: string;
    };
    source.nested[0]!.value = 1;
    source.text = "after";

    expect(snapshot).toEqual({ nested: [{ value: 0 }], text: "before" });
    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.nested)).toBe(true);
    expect(Object.isFrozen(snapshot.nested[0])).toBe(true);
  });

  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  const hostileValues: readonly [string, unknown][] = [
    ["function", () => undefined],
    ["symbol", Symbol("value")],
    ["bigint", 1n],
    ["date", new Date(0)],
    ["map", new Map([["key", "value"]])],
    ["cycle", cyclic],
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["unsafe integer", 2 ** 53],
    ["sparse array", Array(1)],
  ];

  it.each(hostileValues)("rejects hostile %s values with a redacted typed error", (_label, bad) => {
    const secret = "sk-hostile-durable-secret";

    let error: unknown;
    try {
      durableJsonSnapshot({ secret, bad }, "tool_result", 64 * 1024);
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(InvalidDurableValueError);
    expect(error).toMatchObject({ code: "INVALID_DURABLE_VALUE", subject: "tool_result" });
    expect(String(error)).not.toContain(secret);
  });

  it("rejects accessors without invoking their getter", () => {
    let getterCalls = 0;
    const value = {};
    Object.defineProperty(value, "secret", {
      enumerable: true,
      get() {
        getterCalls++;
        return "sk-getter-secret";
      },
    });

    expect(() => durableJsonSnapshot(value, "event_metadata", 1_024)).toThrow(
      InvalidDurableValueError,
    );
    expect(getterCalls).toBe(0);
  });

  it.each([false, true])("enforces exact UTF-8 bytes (multibyte=%s)", (multibyte) => {
    const maxBytes = 256;
    const emptySize = new TextEncoder().encode('{"value":""}').byteLength;
    const remaining = maxBytes - emptySize;
    const value = multibyte
      ? "😀".repeat(Math.floor(remaining / 4)) + "x".repeat(remaining % 4)
      : "x".repeat(remaining);

    expect(durableJsonSnapshot({ value }, "workflow_result", maxBytes)).toEqual({ value });
    expect(() => durableJsonSnapshot({ value: `${value}x` }, "workflow_result", maxBytes)).toThrow(
      DurableJsonLimitError,
    );
    try {
      durableJsonSnapshot({ value: `${value}x` }, "workflow_result", maxBytes);
    } catch (error) {
      expect(error).toMatchObject({
        code: "EVENT_PAYLOAD_TOO_LARGE",
        subject: "workflow_result",
        maxBytes,
      });
    }
  });

  it("rejects a subject outside the closed durable vocabulary", () => {
    expect(() => durableJsonSnapshot({}, "not_closed", 1)).toThrow(/durable JSON subject/i);
  });
});
