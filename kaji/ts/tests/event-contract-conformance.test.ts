import { readFileSync } from "node:fs";

import Ajv2020, { type ErrorObject } from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";

import {
  EventSchemaIncompatibleError,
  EventType,
  SessionCreated,
  validateNewEvent,
  validateStoredEvent,
} from "@/index";

const contracts = new URL("../../contracts/events/", import.meta.url);
const valid = JSON.parse(readFileSync(new URL("conformance.json", contracts), "utf8")) as {
  events: Record<string, unknown>[];
};
const invalid = JSON.parse(
  readFileSync(new URL("conformance-invalid.json", contracts), "utf8"),
) as {
  cases: Array<{
    name: string;
    kind: "new" | "stored";
    event: Record<string, unknown>;
    path: string;
  }>;
};

function errorPointers(errors: ErrorObject[] | null | undefined): Set<string> {
  const pointers = new Set<string>();
  for (const error of errors ?? []) {
    if (error.keyword === "required") {
      pointers.add(`${error.instancePath}/${String(error.params.missingProperty)}`);
    } else if (error.keyword === "unevaluatedProperties") {
      pointers.add(`${error.instancePath}/${String(error.params.unevaluatedProperty)}`);
    } else {
      pointers.add(error.instancePath || "/");
    }
  }
  return pointers;
}

function canonicalValidators() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  return {
    new: ajv.compile(
      JSON.parse(readFileSync(new URL("new-kaji-event-v1.schema.json", contracts), "utf8")),
    ),
    stored: ajv.compile(
      JSON.parse(readFileSync(new URL("stored-kaji-event-v1.schema.json", contracts), "utf8")),
    ),
  };
}

describe("frozen event wire contract", () => {
  it("keeps constructor defaults separate from raw validation", () => {
    const constructed = SessionCreated.parse({
      type: EventType.SESSION_CREATED,
      session_id: "s",
    });
    expect(constructed.id).not.toBe("");
    expect(constructed.version).toBe("1.0");
    expect(constructed.timestamp).toBeTypeOf("number");

    expect(() => validateNewEvent({ type: EventType.SESSION_CREATED, session_id: "s" })).toThrow(
      expect.objectContaining({ code: "EVENT_SCHEMA_INCOMPATIBLE", path: "/id" }),
    );
  });

  it("accepts every positive fixture in canonical and runtime validators", () => {
    const storedSchema = JSON.parse(
      readFileSync(new URL("stored-kaji-event-v1.schema.json", contracts), "utf8"),
    );
    const newSchema = JSON.parse(
      readFileSync(new URL("new-kaji-event-v1.schema.json", contracts), "utf8"),
    );
    const canonical = new Ajv2020({ allErrors: true, strict: false }).compile(storedSchema);
    const canonicalNew = new Ajv2020({ allErrors: true, strict: false }).compile(newSchema);

    for (const event of valid.events) {
      expect(canonical(event), JSON.stringify(canonical.errors)).toBe(true);
      expect(validateStoredEvent(event).type).toBe(event.type);
      const draft = { ...event };
      delete draft.sequence;
      expect(canonicalNew(draft), JSON.stringify(canonicalNew.errors)).toBe(true);
      expect(validateNewEvent(draft).type).toBe(event.type);
    }
  });

  it("rejects every negative fixture at the same normalized pointer", () => {
    const schemas = {
      new: JSON.parse(readFileSync(new URL("new-kaji-event-v1.schema.json", contracts), "utf8")),
      stored: JSON.parse(
        readFileSync(new URL("stored-kaji-event-v1.schema.json", contracts), "utf8"),
      ),
    };
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    const canonical = { new: ajv.compile(schemas.new), stored: ajv.compile(schemas.stored) };

    for (const fixture of invalid.cases) {
      const schemaValidator = canonical[fixture.kind];
      expect(schemaValidator(fixture.event), fixture.name).toBe(false);
      expect(errorPointers(schemaValidator.errors), fixture.name).toContain(fixture.path);

      const runtimeValidator = fixture.kind === "stored" ? validateStoredEvent : validateNewEvent;
      try {
        runtimeValidator(fixture.event);
        throw new Error(`expected ${fixture.name} to fail`);
      } catch (error) {
        expect(error, fixture.name).toBeInstanceOf(EventSchemaIncompatibleError);
        expect((error as EventSchemaIncompatibleError).path, fixture.name).toBe(fixture.path);
      }
    }
  });

  it("aligns populated, null, and omitted usage fields across wire validators", () => {
    const canonical = canonicalValidators();
    const usageCases = [
      { tokens: { input: 1, output: 2 }, cost_usd: 0.25 },
      { tokens: null, cost_usd: null },
      {},
    ];
    const completionCases = [
      { type: EventType.AGENT_MESSAGE_COMPLETED, content: "done" },
      {
        type: EventType.TOOL_CALL_COMPLETED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "call",
        result: { ok: true },
      },
    ];
    for (const completion of completionCases) {
      for (const usage of usageCases) {
        const draft = {
          id: "event",
          version: "1.0",
          timestamp: 0,
          session_id: "session",
          ...completion,
          ...usage,
        };
        expect(canonical.new(draft), JSON.stringify(canonical.new.errors)).toBe(true);
        expect(validateNewEvent(draft).type).toBe(completion.type);
        const stored = { ...draft, sequence: 1 };
        expect(canonical.stored(stored), JSON.stringify(canonical.stored.errors)).toBe(true);
        expect(validateStoredEvent(stored).type).toBe(completion.type);
      }
    }
  });

  it("aligns 200/201 astral-code-point boundaries across wire validators", () => {
    const canonical = canonicalValidators();
    const boundedCases = [
      {
        type: EventType.AGENT_TURN_FAILED,
        turn_id: "turn",
        field: "error",
      },
      {
        type: EventType.TOOL_CALL_FAILED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "call",
        field: "error",
      },
      {
        type: EventType.TOOL_APPROVAL_REJECTED,
        turn_id: "turn",
        tool_name: "tool",
        tool_call_id: "call",
        error_code: "APPROVAL_REJECTED",
        field: "reason",
      },
    ];
    for (const bounded of boundedCases) {
      const { field, ...event } = bounded;
      const draft = {
        id: "event",
        version: "1.0",
        timestamp: 0,
        session_id: "session",
        ...event,
        [field]: "😀".repeat(200),
      };
      expect(canonical.new(draft), JSON.stringify(canonical.new.errors)).toBe(true);
      expect(() => validateNewEvent(draft)).not.toThrow();
      const stored = { ...draft, sequence: 1 };
      expect(canonical.stored(stored), JSON.stringify(canonical.stored.errors)).toBe(true);
      expect(() => validateStoredEvent(stored)).not.toThrow();

      const rejectedDraft = { ...draft, [field]: "😀".repeat(201) };
      expect(canonical.new(rejectedDraft)).toBe(false);
      expect(() => validateNewEvent(rejectedDraft)).toThrow(
        expect.objectContaining({ code: "EVENT_SCHEMA_INCOMPATIBLE", path: `/${field}` }),
      );
      const rejectedStored = { ...rejectedDraft, sequence: 1 };
      expect(canonical.stored(rejectedStored)).toBe(false);
      expect(() => validateStoredEvent(rejectedStored)).toThrow(
        expect.objectContaining({ code: "EVENT_SCHEMA_INCOMPATIBLE", path: `/${field}` }),
      );
    }
  });
});
