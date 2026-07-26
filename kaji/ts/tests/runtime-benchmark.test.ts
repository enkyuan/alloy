import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const benchmark = fileURLToPath(new URL("../benchmarks/runtime-benchmark.ts", import.meta.url));

function reducerProbe(mode: "aggregate" | "semantic-drift"): {
  readonly seeds: readonly number[];
  readonly rejected?: boolean;
  readonly result?: Readonly<Record<string, number>>;
} {
  return JSON.parse(
    execFileSync(
      process.env.KAJI_TEST_BUN ?? "bun",
      [benchmark, "--internal-test-repeat-reducer", mode],
      {
        encoding: "utf8",
      },
    ),
  ) as {
    readonly seeds: readonly number[];
    readonly rejected?: boolean;
    readonly result?: Readonly<Record<string, number>>;
  };
}

describe("runtime benchmark repetition reducer", () => {
  it("uses deterministic seeds and reduces only timing and memory measurements", () => {
    const probe = reducerProbe("aggregate");

    expect(probe.seeds).toEqual([13, 14, 15]);
    expect(probe.result).toEqual({
      durationMs: 7,
      incrementalRssBytes: 12,
      completed: 100,
      turns: 25,
      peakMiB: 9,
      benchmarkRepetitions: 3,
    });
  });

  it("fails on intermediate semantic drift before a later valid result can hide it", () => {
    const probe = reducerProbe("semantic-drift");

    expect(probe).toEqual({
      seeds: [21, 22],
      rejected: true,
    });
  });
});
