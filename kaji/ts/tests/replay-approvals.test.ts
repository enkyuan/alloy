/**
 * Tests for `replaySession`'s approval-lifecycle projection. Builds events
 * through Zod's `KajiEvent.parse` so the shapes match the wire format.
 */
import { describe, expect, it } from "vitest";
import { EventType } from "@/events/types";
import { KajiEvent } from "@/events/schemas";
import { replayLegacySession } from "@/sessions/replay";

const SESSION_ID = "s1";

function makeEvent(input: Record<string, unknown>) {
  return KajiEvent.parse({ session_id: SESSION_ID, ...input });
}

describe("replaySession approval projection", () => {
  it("tracks approved, rejected, and still-pending approvals by tool_call_id", () => {
    const events = [
      makeEvent({ type: EventType.SESSION_CREATED }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REQUESTED,
        tool_name: "ship_it",
        tool_call_id: "c1",
        tool_args: {},
        risk: "write",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_APPROVED,
        tool_name: "ship_it",
        tool_call_id: "c1",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REQUESTED,
        tool_name: "delete_account",
        tool_call_id: "c2",
        tool_args: { confirm: true },
        risk: "destructive",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REJECTED,
        tool_name: "delete_account",
        tool_call_id: "c2",
        reason: "Rejected by approval handler",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REQUESTED,
        tool_name: "send_email",
        tool_call_id: "c3",
        tool_args: { to: "x" },
        risk: "write",
      }),
    ];

    const state = replayLegacySession(events);
    expect(state.approvedToolCallIds.has("c1")).toBe(true);
    expect(state.rejectedToolCallIds.has("c2")).toBe(true);
    expect(state.pendingApprovals.has("c3")).toBe(true);
    expect(state.pendingApprovals.has("c1")).toBe(false);
    expect(state.pendingApprovals.has("c2")).toBe(false);
  });

  it("defaults all three sets to empty when no approval events occur", () => {
    const state = replayLegacySession([makeEvent({ type: EventType.SESSION_CREATED })]);
    expect(state.pendingApprovals.size).toBe(0);
    expect(state.approvedToolCallIds.size).toBe(0);
    expect(state.rejectedToolCallIds.size).toBe(0);
  });
});
