import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { StoredKajiEvent, validateStoredEvent } from "@/events/schemas";
import { replaySession } from "@/sessions/replay";

const __dirname = dirname(fileURLToPath(import.meta.url));
const contractPath = resolve(__dirname, "../../contracts/beta-core-v1.json");
const canonicalPath = resolve(__dirname, "../../contracts/beta-core-v1.json");
const packagedPath = resolve(__dirname, "../contracts/beta-core-v1.json");
const eventFixturePath = resolve(__dirname, "../../contracts/events/conformance.json");

describe("production-beta contract", () => {
  it("pins the production-beta compatibility defaults", () => {
    const contract = JSON.parse(readFileSync(contractPath, "utf8"));

    expect(contract.runtime).toMatchObject({
      sameSessionTurns: "serialized",
      maxToolIterations: 5,
      contextWindowTurns: 32,
      turnTimeoutMs: 120_000,
      providerCancellationGraceMs: 5_000,
      providerTextMaxBytes: 262_144,
      providerToolArgumentsMaxBytes: 65_536,
      providerResponseMaxBytes: 524_288,
      providerToolCallsMax: 64,
    });
    expect(contract.tools).toMatchObject({ maxConcurrency: 4, timeoutMs: 30_000 });
    expect(contract.events).toMatchObject({
      subscriberQueueCapacity: 1024,
      maxDurableToolResultBytes: 65_536,
      maxDurableEventBytes: 1_048_576,
      inMemoryStoreMaxEventsPerSession: 10_000,
    });
  });

  it("ships a byte-identical package copy", () => {
    expect(readFileSync(packagedPath)).toEqual(readFileSync(canonicalPath));
  });

  it("parses and replays every canonical approval lifecycle fixture row", () => {
    const fixture = JSON.parse(readFileSync(eventFixturePath, "utf8")) as { events: unknown[] };
    const events = fixture.events.map(validateStoredEvent);
    expect(events).toHaveLength(40);
    const state = replaySession(events);
    expect(state.isActive).toBe(false);
    expect(state.pendingApprovals.size).toBe(0);
    expect(state.approvedApprovals.size).toBe(1);
    expect(state.rejectedApprovals.size).toBe(4);
  });

  it("rejects blank approval reasons without transforming stored text", () => {
    const base = {
      type: "tool.approval.rejected",
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      error_code: "APPROVAL_REJECTED",
    };
    expect(() => StoredKajiEvent.parse({ ...base, reason: "   ", sequence: 1 })).toThrow();
    const preserved = StoredKajiEvent.parse({
      ...base,
      reason: "  operator rejected  ",
      sequence: 1,
    });
    expect(preserved.type).toBe("tool.approval.rejected");
    if (preserved.type === "tool.approval.rejected") {
      expect(preserved.reason).toBe("  operator rejected  ");
    }
    expect(() =>
      StoredKajiEvent.parse({ ...base, reason: "😀".repeat(200), sequence: 1 }),
    ).not.toThrow();
    expect(() =>
      StoredKajiEvent.parse({ ...base, reason: "😀".repeat(201), sequence: 1 }),
    ).toThrow();
  });

  it("enforces canonical tool lifecycle identifiers and bounded public errors", () => {
    const base = {
      session_id: "session",
      turn_id: "turn",
      tool_name: "tool",
      tool_call_id: "call",
      sequence: 1,
    };
    expect(() =>
      StoredKajiEvent.parse({
        ...base,
        type: "tool.call.requested",
        tool_name: "",
        tool_args: {},
      }),
    ).toThrow();
    expect(() =>
      StoredKajiEvent.parse({ ...base, type: "tool.call.started", tool_call_id: "" }),
    ).toThrow();
    expect(() => StoredKajiEvent.parse({ ...base, type: "tool.call.failed", error: "" })).toThrow();
    expect(() =>
      StoredKajiEvent.parse({
        ...base,
        type: "tool.call.failed",
        error: "😀".repeat(200),
      }),
    ).not.toThrow();
    expect(() =>
      StoredKajiEvent.parse({
        ...base,
        type: "tool.call.failed",
        error: "😀".repeat(201),
      }),
    ).toThrow();
  });
});
