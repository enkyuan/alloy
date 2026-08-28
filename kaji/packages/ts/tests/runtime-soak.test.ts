import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { expect, it } from "vitest";

import { CancellationError, EventType } from "@irogane/kaji";
import { countObservedCancellation, countObservedTimeout } from "../benchmarks/runtime-soak";

const execute = promisify(execFile);
const soak = fileURLToPath(new URL("../benchmarks/runtime-soak.ts", import.meta.url));

it("counts only the runtime cancellation error", () => {
  expect(countObservedCancellation({ status: "rejected", reason: new CancellationError() })).toBe(
    1,
  );
  expect(() =>
    countObservedCancellation({ status: "rejected", reason: new Error("foreign") }),
  ).toThrow("unexpected cancellation outcome");
  expect(() => countObservedCancellation({ status: "fulfilled", value: undefined })).toThrow(
    "unexpected cancellation outcome",
  );
});

it("counts timeout scenarios only from their exact failed tool event", () => {
  const timeout = {
    status: "fulfilled" as const,
    value: {
      events: [
        {
          type: EventType.TOOL_CALL_FAILED,
          tool_name: "cooperative-timeout",
          error_code: "TOOL_TIMEOUT",
          outcome: "unknown",
        },
      ],
    },
  };

  expect(countObservedTimeout(timeout, "cooperative-timeout")).toBe(1);
  expect(() => countObservedTimeout(timeout, "foreign-timeout")).toThrow(
    "unexpected timeout outcome",
  );
  expect(() =>
    countObservedTimeout(
      {
        status: "fulfilled",
        value: {
          events: [
            {
              type: EventType.TOOL_CALL_COMPLETED,
              tool_name: "cooperative-timeout",
            },
          ],
        },
      },
      "cooperative-timeout",
    ),
  ).toThrow("unexpected timeout outcome");
  expect(() =>
    countObservedTimeout(
      {
        status: "rejected",
        reason: new Error("foreign"),
      },
      "cooperative-timeout",
    ),
  ).toThrow("unexpected timeout outcome");
});

it("samples heap only after the live shared session is closed", async () => {
  const source = await readFile(soak, "utf8");

  expect(source).toMatch(
    /if \(batch % 100 === 0\) \{\s+await slowSubscriber\.return\?\.\(\);\s+await closeSession\(sharedSession\);\s+const observedElapsedMs = elapsedMs\(started\);\s+const observedSampleBucket = Math\.floor\(observedElapsedMs \/ 60_000\);\s+if \(observedSampleBucket > lastSampleBucket\) \{\s+sample\(observedElapsedMs\);\s+lastSampleBucket = observedSampleBucket;\s+}\s+sharedSession = `shared-\$\{\+\+sharedGeneration}`;\s+slowSubscriber = committer\.subscribe\(sharedSession\);\s+}/,
  );
});

it("reclaims closed sessions during sustained churn", async () => {
  const { stdout } = await execute("bun", [soak, "--minutes", "0.05", "--seed", "13", "--json"], {
    maxBuffer: 4 * 1024 * 1024,
    timeout: 15_000,
  });
  const result = JSON.parse(stdout.trim()) as {
    attemptedTurns: number;
    completedTurns: number;
    failedTurns: number;
    terminalOutcomes: { completed: number; failed: number; cancelled: number };
    internal: {
      projectionCacheSize: number;
      ledgerSize: number;
      ledgerCounts: { running: number };
      gcAvailable: boolean;
      scenarios: { crossSessionTurns: number; sessionClosures: number };
    };
    memorySamples: Array<{ heapUsedMiB: number; heapTotalMiB: number }>;
  };

  expect(result.attemptedTurns).toBe(result.completedTurns + result.failedTurns);
  expect(result.completedTurns).toBeGreaterThan(0);
  expect(result.failedTurns).toBe(result.terminalOutcomes.cancelled);
  expect(result.terminalOutcomes.failed).toBe(0);
  expect(result.internal.projectionCacheSize).toBe(0);
  expect(result.internal.ledgerSize).toBe(0);
  expect(result.internal.ledgerCounts.running).toBe(0);
  expect(result.internal.gcAvailable).toBe(true);
  expect(result.memorySamples.length).toBeGreaterThan(0);
  for (const sample of result.memorySamples) {
    expect(Number.isFinite(sample.heapUsedMiB)).toBe(true);
    expect(Number.isFinite(sample.heapTotalMiB)).toBe(true);
    expect(sample.heapUsedMiB).toBeGreaterThan(0);
    expect(sample.heapTotalMiB).toBeGreaterThanOrEqual(sample.heapUsedMiB);
  }
  expect(result.internal.scenarios.crossSessionTurns).toBeGreaterThan(0);
  expect(result.internal.scenarios.sessionClosures).toBeGreaterThanOrEqual(
    result.internal.scenarios.crossSessionTurns,
  );
}, 20_000);
