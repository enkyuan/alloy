import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { EventType, KajiEvent } from "@/index";

const lifecycleContract = {
  inMemorySessionAdmission: "fail_closed_until_explicit_purge",
  purgedSessionReuse: "fresh_sequence",
  purgeClosesExistingSubscribers: true,
  purgeFencesDirectStoreOperations: true,
  postDeleteCleanup: "tombstone_until_converged",
  splitDeliveryPurge: "unsupported",
} as const;

function readFixture(name: string): unknown {
  return JSON.parse(
    readFileSync(new URL(`../../../fixtures/events/${name}`, import.meta.url), "utf8"),
  );
}

describe("shared event schema fixtures", () => {
  it("pins and packages the cross-SDK session lifecycle contract byte-for-byte", () => {
    for (const name of ["beta-core-v1.json", "feature-tiers-v1.json"] as const) {
      const canonical = readFileSync(new URL(`../../../contracts/${name}`, import.meta.url));
      expect(
        readFileSync(new URL(`../../python/src/kaji/contracts/${name}`, import.meta.url)),
      ).toEqual(canonical);
      expect(readFileSync(new URL(`../contracts/${name}`, import.meta.url))).toEqual(canonical);
    }

    const contract = JSON.parse(
      readFileSync(new URL("../../../contracts/beta-core-v1.json", import.meta.url), "utf8"),
    ) as { events: Record<string, unknown> };
    expect(contract.events).toMatchObject(lifecycleContract);
  });

  it("parses an agent message completed event with usage and cost", () => {
    const event = KajiEvent.parse(readFixture("agent-message-completed-with-usage.json"));

    expect(event.type).toBe(EventType.AGENT_MESSAGE_COMPLETED);
    if (event.type === EventType.AGENT_MESSAGE_COMPLETED) {
      expect(event.tokens).toEqual({ input: 12, output: 7 });
      expect(event.cost_usd).toBeGreaterThan(0);
    }
  });

  it("parses a tool call completed event with usage and cost", () => {
    const event = KajiEvent.parse({
      ...(readFixture("tool-call-completed-with-usage.json") as Record<string, unknown>),
      turn_id: "turn-1",
    });

    expect(event.type).toBe(EventType.TOOL_CALL_COMPLETED);
    if (event.type === EventType.TOOL_CALL_COMPLETED) {
      expect(event.tokens).toEqual({ input: 4, output: 2 });
      expect(event.cost_usd).toBeGreaterThan(0);
    }
  });
});
