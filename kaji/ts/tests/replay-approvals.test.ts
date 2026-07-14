import { describe, expect, it } from "vitest";

import {
  NewKajiEvent,
  StoredKajiEvent,
  type NewKajiEvent as NewKajiEventType,
} from "@/events/schemas";
import { EventType } from "@/events/types";
import { approvalKey, applyEvent, createSessionState, replaySession } from "@/sessions/replay";

const SESSION_ID = "s1";

function makeEvent(input: Record<string, unknown>) {
  return NewKajiEvent.parse({ session_id: SESSION_ID, ...input });
}

function storeEvents(events: readonly NewKajiEventType[]) {
  return events.map((event, index) => StoredKajiEvent.parse({ ...event, sequence: index + 1 }));
}

function approvalRequest(turnId: string, callId: string, toolName: string) {
  return makeEvent({
    type: EventType.TOOL_APPROVAL_REQUESTED,
    turn_id: turnId,
    tool_name: toolName,
    tool_call_id: callId,
    tool_args: {},
    risk: "write",
  });
}

describe("approval replay projection", () => {
  it("keys decisions by turn, call, and tool rather than call id alone", () => {
    const events = [
      makeEvent({ type: EventType.SESSION_CREATED }),
      approvalRequest("turn-1", "reused", "ship"),
      makeEvent({
        type: EventType.TOOL_APPROVAL_APPROVED,
        turn_id: "turn-1",
        tool_name: "ship",
        tool_call_id: "reused",
      }),
      approvalRequest("turn-2", "reused", "ship"),
      approvalRequest("turn-2", "reused", "refund"),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REJECTED,
        turn_id: "turn-2",
        tool_name: "refund",
        tool_call_id: "reused",
        error_code: "APPROVAL_REJECTED",
        reason: "Rejected by operator",
      }),
    ];

    const state = replaySession(storeEvents(events));
    expect(state.approvedApprovals).toEqual(new Set([approvalKey("turn-1", "reused", "ship")]));
    expect(state.rejectedApprovals).toEqual(
      new Map([[approvalKey("turn-2", "reused", "refund"), "APPROVAL_REJECTED"]]),
    );
    expect(state.pendingApprovals).toEqual(new Set([approvalKey("turn-2", "reused", "ship")]));
  });

  it("drains timeout/cancel/unavailable decisions through the rejection path", () => {
    const events = [makeEvent({ type: EventType.SESSION_CREATED })];
    for (const [index, errorCode] of [
      "APPROVAL_TIMEOUT",
      "TOOL_CANCELLED",
      "APPROVAL_UNAVAILABLE",
    ].entries()) {
      const turnId = `turn-${index}`;
      const callId = `call-${index}`;
      events.push(
        approvalRequest(turnId, callId, "ship"),
        makeEvent({
          type: EventType.TOOL_APPROVAL_REJECTED,
          turn_id: turnId,
          tool_name: "ship",
          tool_call_id: callId,
          error_code: errorCode,
          reason: "Approval did not complete",
        }),
      );
    }

    const state = replaySession(storeEvents(events));
    expect(state.pendingApprovals.size).toBe(0);
    expect(state.rejectedApprovals.size).toBe(3);
  });

  it("produces identical cold and incremental approval state", () => {
    const drafts = [
      makeEvent({ type: EventType.SESSION_CREATED }),
      approvalRequest("turn", "call", "ship"),
      makeEvent({
        type: EventType.TOOL_APPROVAL_APPROVED,
        turn_id: "turn",
        tool_name: "ship",
        tool_call_id: "call",
      }),
    ];
    const stored = storeEvents(drafts);
    const cold = replaySession(stored);
    const warm = createSessionState(SESSION_ID);
    for (const event of stored) applyEvent(warm, event);

    expect(warm.pendingApprovals).toEqual(cold.pendingApprovals);
    expect(warm.approvedApprovals).toEqual(cold.approvedApprovals);
    expect(warm.rejectedApprovals).toEqual(cold.rejectedApprovals);
  });

  it("keeps the first decision when duplicate or opposite decisions follow", () => {
    const events = [
      makeEvent({ type: EventType.SESSION_CREATED }),
      approvalRequest("turn", "call", "ship"),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REJECTED,
        turn_id: "turn",
        tool_name: "ship",
        tool_call_id: "call",
        error_code: "APPROVAL_TIMEOUT",
        reason: "Timed out",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_APPROVED,
        turn_id: "turn",
        tool_name: "ship",
        tool_call_id: "call",
      }),
      makeEvent({
        type: EventType.TOOL_APPROVAL_REJECTED,
        turn_id: "turn",
        tool_name: "ship",
        tool_call_id: "call",
        error_code: "APPROVAL_REJECTED",
        reason: "Late opposite decision",
      }),
    ];

    const state = replaySession(storeEvents(events));
    const key = approvalKey("turn", "call", "ship");
    expect(state.pendingApprovals.size).toBe(0);
    expect(state.approvedApprovals.has(key)).toBe(false);
    expect(state.rejectedApprovals).toEqual(new Map([[key, "APPROVAL_TIMEOUT"]]));
  });
});
