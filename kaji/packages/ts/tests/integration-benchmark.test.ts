import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  benchmarkInputDigest,
  canonicalBenchmarkJson,
  INTEGRATION_BENCHMARK_CASES,
  loadIntegrationBenchmarkBudgets,
  runIntegrationBenchmarkCase,
  type IntegrationBenchmarkCase,
} from "../scripts/integration-benchmark";

const budgetsPath = new URL("../../../benchmarks/integration-budgets.json", import.meta.url);
const budgets = loadIntegrationBenchmarkBudgets(budgetsPath);

const expectedDigests: Readonly<Record<IntegrationBenchmarkCase, string>> = {
  fixedOriginPreflight: "aa7d6eecaf6c4a469a5224a23933ea1182286044643f8859874775a3af5df8e7",
  fixedOriginCapRejection: "a4b4289307f2f54631116c0a05db56dfa48aba899ae671327f4c943f0e48391a",
  githubDtoMaxBounds: "d0bbeaf2597ae71c2b8b1ff4c279149a18da0ebeb81d9df247323ef99a867089",
  keychainRecordParse: "a8a7b8b0530289ef9be67ecda8803439bf5714fa3ab8fd8d86df79ad0642bdf1",
  oauthRefreshSingleFlight: "eb614f8ecd21653faab7a2995eab7601c3051bd50c9d3eb9707af6da3fd41d57",
};

function expectedSemantics(
  caseName: IntegrationBenchmarkCase,
  input: Readonly<Record<string, unknown>>,
): Readonly<Record<string, number>> {
  switch (caseName) {
    case "fixedOriginPreflight":
      return {
        safeRequests: 1,
        hostileRequests: 0,
        rejected: 1,
        responseBytes: input.responseBytes as number,
      };
    case "fixedOriginCapRejection":
      return {
        requests: 1,
        rejected: 1,
        closed: 1,
        limitBytes: input.limitBytes as number,
        observedBytes: (input.limitBytes as number) + (input.overflowBytes as number),
      };
    case "githubDtoMaxBounds":
      return {
        rows: 20,
        titleCharacters: 256,
        bodyPreviewBytes: 1_024,
        serializedBytes: 26_762,
      };
    case "keychainRecordParse":
      return { records: 1, processCalls: 1, recordBytes: 15_157, scopes: 1 };
    case "oauthRefreshSingleFlight":
      return { waiters: 8, httpCalls: 1, saveCalls: 1, uniqueTokens: 1 };
  }
}

describe("integration benchmark case runner", () => {
  it("keeps the five reviewed cases with no benchmark deviations", () => {
    const raw = JSON.parse(readFileSync(budgetsPath, "utf8")) as {
      cases: readonly { name: string }[];
      deviations: readonly unknown[];
    };

    expect(raw.cases.map(({ name }) => name)).toEqual(INTEGRATION_BENCHMARK_CASES);
    expect(INTEGRATION_BENCHMARK_CASES).not.toContain("gmailMimeMaxBounds");
    expect(raw.deviations).toEqual([]);
  });

  it("uses stable recursively sorted input hashing", () => {
    expect(canonicalBenchmarkJson({ z: 1, a: { d: 2, b: 1 } })).toBe('{"a":{"b":1,"d":2},"z":1}');
    for (const testCase of budgets.cases) {
      expect(benchmarkInputDigest(testCase.input)).toBe(expectedDigests[testCase.name]);
    }
  });

  it.each(budgets.cases)(
    "runs $name with only deterministic injected dependencies",
    async (testCase) => {
      const result = await runIntegrationBenchmarkCase({
        caseName: testCase.name,
        input: testCase.input,
        warmups: 1,
        batches: 1,
        samplesPerBatch: 2,
      });

      expect(result).toMatchObject({
        schemaVersion: 1,
        runtime: "typescript",
        case: testCase.name,
        inputSha256: expectedDigests[testCase.name],
        warmups: 1,
        semantics: expectedSemantics(testCase.name, testCase.input),
      });
      expect(result.batches).toHaveLength(1);
      expect(result.batches[0]).toHaveLength(2);
      expect(result.batches[0]!.every((value) => Number.isFinite(value) && value >= 0)).toBe(true);
    },
  );
});
