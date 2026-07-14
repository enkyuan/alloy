import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  calculateCostFromRatesUsdCanonical,
  calculateCostUsd,
  calculateCostUsdCanonical,
  lookupCost,
} from "@/providers/costs";

interface CostCase {
  name: string;
  model?: string;
  rates?: { inputPer1M: string; outputPer1M: string };
  inputTokens: number;
  outputTokens: number;
  expectedCanonicalUsd: string;
}

interface CostFixture {
  cases: CostCase[];
  invalidTokenCounts: Array<{ name: string; value: unknown }>;
  invalidRates: Array<{ name: string; kind: "number" | "string"; value: string }>;
}

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(
  readFileSync(resolve(__dirname, "../../contracts/providers/cost-conformance.json"), "utf8"),
) as CostFixture;

describe("model cost table", () => {
  it("prices the recommended first live OpenAI model", () => {
    expect(lookupCost("gpt-5.4-mini")).toEqual({
      inputPer1M: 0.75,
      outputPer1M: 4.5,
    });
    expect(calculateCostUsd("gpt-5.4-mini", 1_000_000, 1_000_000)).toBe(5.25);
  });

  it("accepts snapshots without guessing model families", () => {
    expect(lookupCost("gpt-5.4-mini-2026-04-15")).toEqual(lookupCost("gpt-5.4-mini"));
    expect(lookupCost("gemini-3.5-flash-001")).toEqual(lookupCost("gemini-3.5-flash"));
    expect(lookupCost("claude-sonnet-4-60")).toBeUndefined();
    expect(lookupCost("moonshotai/kimi-k2.6")).toBeUndefined();
  });

  it("uses the current Gemini 2.5 Flash standard rate", () => {
    expect(lookupCost("gemini-2.5-flash")).toEqual({ inputPer1M: 0.3, outputPer1M: 2.5 });
  });

  it.each(fixture.cases)("matches the shared $name fixture", (testCase) => {
    const { inputTokens, outputTokens, expectedCanonicalUsd } = testCase;
    let canonical: string;
    if (testCase.rates) {
      canonical = calculateCostFromRatesUsdCanonical(
        inputTokens,
        outputTokens,
        testCase.rates.inputPer1M,
        testCase.rates.outputPer1M,
      );
      expect(
        calculateCostFromRatesUsdCanonical(
          inputTokens,
          outputTokens,
          Number(testCase.rates.inputPer1M),
          Number(testCase.rates.outputPer1M),
        ),
      ).toBe(expectedCanonicalUsd);
    } else {
      canonical = calculateCostUsdCanonical(testCase.model!, inputTokens, outputTokens);
      const result = calculateCostUsd(testCase.model!, inputTokens, outputTokens);
      expect(typeof result).toBe("number");
      expect(result).toBe(Number(expectedCanonicalUsd));
    }
    expect(canonical).toBe(expectedCanonicalUsd);
  });

  it.each(fixture.invalidTokenCounts)("rejects $name token counts", ({ value }) => {
    expect(() => calculateCostUsd("gemini-3.5-flash", value as number, 0)).toThrow();
    expect(() => calculateCostUsd("gemini-3.5-flash", 0, value as number)).toThrow();
  });

  it.each(fixture.invalidRates)("rejects the shared $name rate", ({ kind, value }) => {
    const rate = kind === "number" ? Number(value) : value;
    expect(() => calculateCostFromRatesUsdCanonical(1, 1, rate, "0")).toThrow();
    expect(() => calculateCostFromRatesUsdCanonical(1, 1, "0", rate)).toThrow();
  });
});
