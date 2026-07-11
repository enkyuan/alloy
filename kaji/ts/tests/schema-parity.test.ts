import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { EventType, KajiEvent } from "@/index";

function readFixture(name: string): unknown {
  return JSON.parse(
    readFileSync(new URL(`../../fixtures/events/${name}`, import.meta.url), "utf8"),
  );
}

describe("shared event schema fixtures", () => {
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
