// This is YOUR no-network GitHub owner fixture test. Edit it.

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const closedOutcomes = new Set([
  "success",
  "missing_auth",
  "rate_limit",
  "approval_rejected",
  "connection_lost_after_dispatch",
]);

export function scriptedOutcome(name: string): string {
  if (!closedOutcomes.has(name)) throw new Error("unknown scripted GitHub outcome");
  const fixture = JSON.parse(
    readFileSync(new URL("../owner-fixtures.json", import.meta.url), "utf8"),
  ) as { outcomes: Array<{ name: string; expected: string }> };
  return fixture.outcomes.find((row) => row.name === name)!.expected;
}

describe("GitHub owner fixtures", () => {
  it("keeps scripted outcomes closed and network-free", () => {
    expect([...closedOutcomes].map((name) => [name, scriptedOutcome(name)])).toEqual([
      ["success", "success"],
      ["missing_auth", "INTEGRATION_AUTH_REQUIRED"],
      ["rate_limit", "INTEGRATION_RATE_LIMITED"],
      ["approval_rejected", "APPROVAL_REJECTED"],
      ["connection_lost_after_dispatch", "unknown"],
    ]);
  });
});
