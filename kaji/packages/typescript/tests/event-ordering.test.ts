import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { EventIdConflictError, EventSchemaIncompatibleError } from "@/events/errors";
import {
  KajiEvent,
  NewKajiEvent,
  StoredKajiEvent,
  type StoredKajiEvent as StoredKajiEventType,
} from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import { replaySession } from "@/sessions/replay";

function message(id: string, sessionId = "s1", timestamp = 1) {
  return KajiEvent.parse({
    id,
    type: EventType.USER_MESSAGE,
    session_id: sessionId,
    content: id,
    timestamp,
  });
}

const eventFixturePath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../contracts/events/conformance.json",
);

describe("event ordering contract", () => {
  it("distinguishes new and stored event validation", () => {
    const draft = message("event-1");
    expect(() => NewKajiEvent.parse({ ...draft, sequence: 1 })).toThrow();
    expect(StoredKajiEvent.parse({ ...draft, sequence: 1 }).sequence).toBe(1);
    expect(() => StoredKajiEvent.parse(draft)).toThrow();
    expect(() => StoredKajiEvent.parse({ ...draft, sequence: 0 })).toThrow();
    expect(() => StoredKajiEvent.parse({ ...draft, sequence: 1.5 })).toThrow();
  });

  it("persists the shared session-created conformance fixture", async () => {
    const fixture = JSON.parse(readFileSync(eventFixturePath, "utf8")) as {
      events: unknown[];
    };
    const expected = StoredKajiEvent.parse(fixture.events[0]);
    const { sequence: _, ...draft } = expected;
    const store = new InMemoryEventStore();

    const result = await store.append(NewKajiEvent.parse(draft));

    expect(result).toEqual({ event: expected, inserted: true });
  });

  it("parses the shared turn-failure conformance fixture", () => {
    const fixture = JSON.parse(readFileSync(eventFixturePath, "utf8")) as {
      events: unknown[];
    };
    const failure = StoredKajiEvent.parse(fixture.events[2]);

    expect(failure.type).toBe(EventType.AGENT_TURN_FAILED);
    if (failure.type === EventType.AGENT_TURN_FAILED) {
      expect(failure.turn_id).toBe("turn-1");
      expect(failure.error).toBe("Agent turn failed");
    }
  });

  it("assigns unique contiguous sequences to concurrent appends", async () => {
    const store = new InMemoryEventStore();
    const results = await Promise.all(
      Array.from({ length: 50 }, (_, index) => store.append(message(`event-${index}`))),
    );

    expect(results.map(({ event }) => event.sequence)).toEqual(
      Array.from({ length: 50 }, (_, index) => index + 1),
    );
  });

  it("rejects duplicate ids with a different session", async () => {
    const store = new InMemoryEventStore();
    await store.append(message("same-id", "one"));
    await expect(store.append(message("same-id", "two"))).rejects.toBeInstanceOf(
      EventIdConflictError,
    );
  });

  it("rejects mixed sessions and invalid sequence logs", () => {
    const one = { ...message("one", "s1"), sequence: 1 };
    const two = { ...message("two", "s2"), sequence: 2 };
    expect(() => replaySession([one, two])).toThrow(/mixed sessions/);
    expect(() => replaySession([one, { ...message("duplicate"), sequence: 1 }])).toThrow(
      /Duplicate/,
    );
    expect(() => replaySession([{ ...message("later"), sequence: 2 }, one])).toThrow(
      /Non-monotonic/,
    );
    try {
      replaySession([message("draft")] as StoredKajiEventType[]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/sequence");
    }
  });

  it.each([
    ["session_id", undefined, "/session_id"],
    ["session_id", "", "/session_id"],
    ["sequence", undefined, "/sequence"],
  ] as const)("validates every wire row before log invariants (%s)", (field, value, path) => {
    const rows: Record<string, unknown>[] = [
      { ...message("one"), sequence: 1 },
      { ...message("two"), sequence: 2 },
    ];
    if (value === undefined) delete rows[1]![field];
    else rows[1]![field] = value;

    try {
      replaySession(rows as unknown as StoredKajiEventType[]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect(error).toMatchObject({ code: "EVENT_SCHEMA_INCOMPATIBLE", path });
    }
  });

  it("rejects mixed sequenced and unsequenced rows as a schema incompatibility", () => {
    const one = { ...message("one"), sequence: 1 };
    try {
      replaySession([one, message("draft")] as StoredKajiEventType[]);
      throw new Error("expected incompatible event");
    } catch (error) {
      expect(error).toBeInstanceOf(EventSchemaIncompatibleError);
      expect((error as EventSchemaIncompatibleError).path).toBe("/sequence");
    }
  });
});
