import type * as z from "zod";
import { describe, expect, expectTypeOf, it } from "vitest";

import { AgentTurnFailed, KajiEvent, EventType } from "@/index";

describe("KajiEvent", () => {
  it("applies defaults for id, version, timestamp, metadata", () => {
    const event = KajiEvent.parse({
      type: EventType.USER_MESSAGE,
      session_id: "s1",
      content: "hello",
    });

    expect(event.type).toBe(EventType.USER_MESSAGE);
    expect(event.session_id).toBe("s1");
    expect(event.version).toBe("1.0");
    expect(typeof event.id).toBe("string");
    expect(typeof event.timestamp).toBe("number");
    expect(event.metadata).toEqual({});
  });

  it("discriminates on type and keeps variant fields", () => {
    const event = KajiEvent.parse({
      type: EventType.TOOL_CALL_COMPLETED,
      session_id: "s1",
      tool_name: "get_weather",
      tool_call_id: "c1",
      result: { tempF: 68 },
    });

    expect(event.type).toBe(EventType.TOOL_CALL_COMPLETED);
    if (event.type === EventType.TOOL_CALL_COMPLETED) {
      expect(event.tool_name).toBe("get_weather");
      expect(event.result).toEqual({ tempF: 68 });
    }
  });

  it("rejects unknown fields (strict, matching Pydantic extra=forbid)", () => {
    const parsed = KajiEvent.safeParse({
      type: EventType.USER_MESSAGE,
      session_id: "s1",
      content: "hi",
      bogus: true,
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects an unknown event type", () => {
    const parsed = KajiEvent.safeParse({
      type: "not.a.real.type",
      session_id: "s1",
    });
    expect(parsed.success).toBe(false);
  });

  it("requires bounded public errors and turn identity for terminal failures", () => {
    expectTypeOf<z.input<typeof AgentTurnFailed>["turn_id"]>().toEqualTypeOf<string>();
    expectTypeOf<z.output<typeof AgentTurnFailed>["turn_id"]>().toEqualTypeOf<string>();

    expect(
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        turn_id: "turn-1",
        error: "Agent turn failed",
      }).error,
    ).toBe("Agent turn failed");
    expect(() =>
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        error: "Agent turn failed",
      }),
    ).toThrow();
    expect(() =>
      AgentTurnFailed.parse({
        type: EventType.AGENT_TURN_FAILED,
        session_id: "s1",
        turn_id: "turn-1",
        error: "x".repeat(201),
      }),
    ).toThrow();
  });
});
