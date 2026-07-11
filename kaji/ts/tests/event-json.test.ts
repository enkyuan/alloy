import { describe, expect, it } from "vitest";

import { cloneAndFreezeJson, structurallyEqualJson } from "@/events/json";

describe("event JSON helpers", () => {
  it("rejects cycles in cloning and canonical comparison", () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;

    expect(() => cloneAndFreezeJson(cyclic)).toThrow(/acyclic/i);
    expect(() => structurallyEqualJson(cyclic, cyclic)).toThrow(/acyclic/i);
  });

  it("preserves an own __proto__ key without changing the clone prototype", () => {
    const input = JSON.parse('{"__proto__":{"polluted":true},"safe":1}') as Record<string, unknown>;

    const clone = cloneAndFreezeJson(input);

    expect(Object.getPrototypeOf(clone)).toBe(Object.prototype);
    expect(Object.hasOwn(clone, "__proto__")).toBe(true);
    expect((clone.__proto__ as { readonly polluted: boolean }).polluted).toBe(true);
    expect(({} as { polluted?: boolean }).polluted).toBeUndefined();
  });
});
