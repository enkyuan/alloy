import { describe, expect, it } from "vitest";

import { artifact, validateArtifactRef } from "@/artifacts/types";
import { capabilityResult } from "@/capabilities/result";
import { ArtifactEmitted, ToolCallCompleted } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";

describe("artifact references", () => {
  it("accepts valid refs and custom URI schemes", () => {
    const ref = artifact("refund-1", "ryo/refund", "ryo+test://refunds/1", {
      metadata: { refunded: true },
    });
    expect(ref).toMatchObject({ id: "refund-1", type: "ryo/refund" });
  });

  it.each([
    { id: "", type: "ryo/refund", uri: "ryo://refunds/1" },
    { id: "refund-1", type: "refund", uri: "ryo://refunds/1" },
    { id: "refund-1", type: "ryo/refund", uri: "refunds/1" },
  ])("rejects invalid refs", (value) => {
    expect(() => validateArtifactRef(value)).toThrow();
  });

  it("rejects non-durable metadata and oversized refs", () => {
    expect(() =>
      validateArtifactRef({
        id: "refund-1",
        type: "ryo/refund",
        uri: "ryo://refunds/1",
        metadata: { bad: undefined },
      }),
    ).toThrow();
    expect(() =>
      artifact("refund-1", "ryo/refund", "ryo://refunds/1", {
        metadata: { text: "x".repeat(64 * 1024) },
      }),
    ).toThrow();
  });

  it("supports zero, one, and multiple artifacts but rejects duplicate ids", () => {
    const first = artifact("refund-1", "ryo/refund", "ryo://refunds/1");
    const second = artifact("refund-2", "ryo/refund", "ryo://refunds/2");
    expect(capabilityResult()).toMatchObject({ artifacts: [] });
    expect(capabilityResult({ ok: true }, [first]).artifacts).toHaveLength(1);
    expect(capabilityResult(undefined, [first, second]).artifacts).toHaveLength(2);
    expect(() => capabilityResult(undefined, [first, first])).toThrow(/duplicate artifact id/);
  });

  it("stores artifact events after their tool completion", async () => {
    const store = new InMemoryEventStore();
    const completed = await store.append(
      ToolCallCompleted.parse({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: "session-1",
        turn_id: "turn-1",
        tool_name: "refund",
        tool_call_id: "call-1",
        result: { ok: true },
      }),
    );
    const emitted = await store.append(
      ArtifactEmitted.parse({
        type: EventType.ARTIFACT_EMITTED,
        session_id: "session-1",
        turn_id: "turn-1",
        tool_call_id: "call-1",
        artifact: artifact("refund-1", "ryo/refund", "ryo://refunds/1"),
      }),
    );
    expect(emitted.event.sequence).toBe(completed.event.sequence + 1);
  });
});
