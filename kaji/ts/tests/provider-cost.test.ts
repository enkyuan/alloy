import { describe, expect, it } from "vitest";

import { calculateCostUsd, lookupCost } from "@/providers/costs";

describe("model cost table", () => {
  it("prices the recommended first live OpenAI model", () => {
    expect(lookupCost("gpt-5.4-mini")).toEqual({
      inputPer1M: 0.75,
      outputPer1M: 4.5,
    });
    expect(calculateCostUsd("gpt-5.4-mini", 1_000_000, 1_000_000)).toBe(5.25);
  });
});
