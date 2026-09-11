import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { EventType, KajiEvent } from "@/index";

const sharedContracts = new URL("../../../../contracts/", import.meta.url);
const typeScriptContracts = new URL("../../contracts/", import.meta.url);
const legacyTaskEventTypes = [
  "task.created",
  "task.suspended",
  "task.resumed",
  "task.completed",
  "task.failed",
  "task.cancelled",
] as const;
const legacyTaskSymbols = [
  "InvalidTaskTransitionError",
  "PendingApproval",
  "PendingApprovalSummary",
  "TaskHandle",
  "TaskRuntime",
  "TaskSnapshot",
  "TaskState",
  "projectTask",
] as const;
const legacyPythonTaskSymbols = ["TaskHandle", "TaskRuntime", "TaskSnapshot", "TaskState"] as const;

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
    readFileSync(new URL(`../../../../fixtures/events/${name}`, import.meta.url), "utf8"),
  );
}

describe("shared event schema fixtures", () => {
  it("pins core defaults byte-for-byte and preserves the TypeScript export projection", () => {
    const core = "core/v1/beta.json";
    expect(readFileSync(new URL(core, typeScriptContracts))).toEqual(
      readFileSync(new URL(core, sharedContracts)),
    );

    const tiers = "tiers/v1/features.json";
    const sharedTiers = JSON.parse(readFileSync(new URL(tiers, sharedContracts), "utf8")) as {
      packageSubpaths: { typescript: unknown };
      publicExports: { typescript: unknown };
    };
    const typeScriptTiers = JSON.parse(
      readFileSync(new URL(tiers, typeScriptContracts), "utf8"),
    ) as {
      packageSubpaths: { typescript: unknown };
      publicExports: { typescript: unknown };
    };
    expect(typeScriptTiers.packageSubpaths.typescript).toEqual(
      sharedTiers.packageSubpaths.typescript,
    );
    expect(typeScriptTiers.publicExports.typescript).toEqual(sharedTiers.publicExports.typescript);

    const contract = JSON.parse(
      readFileSync(new URL("core/v1/beta.json", sharedContracts), "utf8"),
    ) as { events: Record<string, unknown> };
    expect(contract.events).toMatchObject(lifecycleContract);
  });

  it("projects Python legacy Task data out of TypeScript package contracts", () => {
    const sharedEvents = JSON.parse(
      readFileSync(new URL("events/v1/cases/valid.json", sharedContracts), "utf8"),
    ) as { events: Array<{ type: string }> };
    const typeScriptEvents = JSON.parse(
      readFileSync(new URL("events/v1/cases/valid.json", typeScriptContracts), "utf8"),
    ) as { events: Array<{ type: string }> };
    const sharedTaskEvents = sharedEvents.events
      .map((event) => event.type)
      .filter((type) => type.startsWith("task."));

    expect(sharedTaskEvents).toEqual(legacyTaskEventTypes);
    expect(typeScriptEvents.events.map((event) => event.type)).not.toEqual(
      expect.arrayContaining([...legacyTaskEventTypes]),
    );
    expect(Object.values(EventType)).not.toEqual(expect.arrayContaining([...legacyTaskEventTypes]));

    const sharedPythonExports = (
      JSON.parse(readFileSync(new URL("tiers/v1/features.json", sharedContracts), "utf8")) as {
        publicExports: { python: { stable: string[] } };
      }
    ).publicExports.python.stable;
    const packagedPythonExports = (
      JSON.parse(readFileSync(new URL("tiers/v1/features.json", typeScriptContracts), "utf8")) as {
        publicExports: { python: { stable: string[] } };
      }
    ).publicExports.python.stable;
    expect(sharedPythonExports).toEqual(expect.arrayContaining([...legacyPythonTaskSymbols]));
    expect(packagedPythonExports).not.toEqual(expect.arrayContaining([...legacyPythonTaskSymbols]));

    for (const name of [
      "events/v1/schema/new.json",
      "events/v1/schema/stored.json",
      "tiers/v1/features.json",
    ] as const) {
      const projection = readFileSync(new URL(name, typeScriptContracts), "utf8");
      for (const type of legacyTaskEventTypes) {
        expect(projection).not.toContain(type);
      }
      for (const symbol of legacyTaskSymbols) {
        expect(projection).not.toContain(symbol);
      }
    }
  });

  it("parses an agent message completed event with usage and cost", () => {
    const event = KajiEvent.parse(readFixture("agent/message-completed.json"));

    expect(event.type).toBe(EventType.AGENT_MESSAGE_COMPLETED);
    if (event.type === EventType.AGENT_MESSAGE_COMPLETED) {
      expect(event.tokens).toEqual({ input: 12, output: 7 });
      expect(event.cost_usd).toBeGreaterThan(0);
    }
  });

  it("parses a tool call completed event with usage and cost", () => {
    const event = KajiEvent.parse({
      ...(readFixture("tool/call-completed.json") as Record<string, unknown>),
      turn_id: "turn-1",
    });

    expect(event.type).toBe(EventType.TOOL_CALL_COMPLETED);
    if (event.type === EventType.TOOL_CALL_COMPLETED) {
      expect(event.tokens).toEqual({ input: 4, output: 2 });
      expect(event.cost_usd).toBeGreaterThan(0);
    }
  });
});
