/**
 * Tests for the approval handler infrastructure (Sub-Plan 1).
 *
 * Covers:
 * - EventApprovalHandler: grant, reject, timeout
 * - AutoApprovalHandler: allow, deny, allowAll
 */
import { describe, it, expect } from "vitest";
import { InMemoryEventStore } from "@/events/store";
import { InMemoryEventCommitter } from "@/events/committer";
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import { AutoApprovalHandler } from "@/runtime/approval/auto";
import type { ToolCall } from "@/providers/base";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: "call-1", name: "my_tool", args: {}, ...overrides };
}

/** Yield to flush microtasks so async handlers can set up subscriptions. */
async function flushMicrotasks(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

// ---------------------------------------------------------------------------
// EventApprovalHandler
// ---------------------------------------------------------------------------

describe("EventApprovalHandler", () => {
  it("grant flow: resolves granted:true when TOOL_APPROVAL_APPROVED is appended", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const handler = new EventApprovalHandler(committer);
    const call = makeCall({ id: "call-grant" });
    const ctx = { sessionId: "session-1" };

    const decisionPromise = handler.request(call, ctx);

    // Let the handler complete the REQUEST append and set up its subscription.
    await flushMicrotasks();

    await committer.commit(
      KajiEvent.parse({
        type: EventType.TOOL_APPROVAL_APPROVED,
        session_id: ctx.sessionId,
        tool_name: call.name,
        tool_call_id: call.id,
      }),
    );

    const decision = await decisionPromise;
    expect(decision.granted).toBe(true);
  });

  it("captures a synchronous approval appended by a request-event subscriber", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const handler = new EventApprovalHandler(committer);
    const call = makeCall({ id: "call-sync" });
    const ctx = { sessionId: "session-sync" };

    const observed = committer.subscribe(ctx.sessionId);
    const approveRequest = (async () => {
      for await (const event of observed) {
        if (event.type === EventType.TOOL_APPROVAL_REQUESTED && event.tool_call_id === call.id) {
          await committer.commit(
            KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_APPROVED,
              session_id: ctx.sessionId,
              tool_name: call.name,
              tool_call_id: call.id,
            }),
          );
          return;
        }
      }
    })();

    await expect(handler.request(call, ctx)).resolves.toEqual({ granted: true });
    await approveRequest;
  });

  it("reject flow: resolves granted:false with reason when TOOL_APPROVAL_REJECTED is appended", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const handler = new EventApprovalHandler(committer);
    const call = makeCall({ id: "call-reject" });
    const ctx = { sessionId: "session-2" };

    const decisionPromise = handler.request(call, ctx);
    await flushMicrotasks();

    await committer.commit(
      KajiEvent.parse({
        type: EventType.TOOL_APPROVAL_REJECTED,
        session_id: ctx.sessionId,
        tool_name: call.name,
        tool_call_id: call.id,
        reason: "Not authorized",
      }),
    );

    const decision = await decisionPromise;
    expect(decision.granted).toBe(false);
    expect(decision.reason).toBe("Not authorized");
  });

  it("timeout: rejects with an error when no decision arrives within timeoutMs", async () => {
    const store = new InMemoryEventStore();
    const handler = new EventApprovalHandler(new InMemoryEventCommitter(store), {
      timeoutMs: 50,
    });
    const call = makeCall({ id: "call-timeout" });
    const ctx = { sessionId: "session-3" };

    await expect(handler.request(call, ctx)).rejects.toThrow("timed out");
  }, 2000);

  it("ignores events for a different tool_call_id", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const handler = new EventApprovalHandler(committer, { timeoutMs: 100 });
    const call = makeCall({ id: "call-target" });
    const ctx = { sessionId: "session-4" };

    const decisionPromise = handler.request(call, ctx);
    await flushMicrotasks();

    // Append an APPROVED for a different call — should be ignored.
    await committer.commit(
      KajiEvent.parse({
        type: EventType.TOOL_APPROVAL_APPROVED,
        session_id: ctx.sessionId,
        tool_name: call.name,
        tool_call_id: "call-other",
      }),
    );

    await expect(decisionPromise).rejects.toThrow("timed out");
  }, 2000);

  it("emits TOOL_APPROVAL_REQUESTED to the store", async () => {
    const store = new InMemoryEventStore();
    const handler = new EventApprovalHandler(new InMemoryEventCommitter(store), {
      timeoutMs: 50,
    });
    const call = makeCall({ id: "call-emit" });
    const ctx = { sessionId: "session-5", risk: "write" };

    // Let the timeout fire naturally; check the emitted event afterwards.
    await expect(handler.request(call, ctx)).rejects.toThrow("timed out");

    const events = await store.getEvents(ctx.sessionId);
    const requestEvent = events.find((e) => e.type === EventType.TOOL_APPROVAL_REQUESTED);
    expect(requestEvent).toBeDefined();
    if (requestEvent?.type === EventType.TOOL_APPROVAL_REQUESTED) {
      expect(requestEvent.tool_call_id).toBe(call.id);
      expect(requestEvent.risk).toBe("write");
    }
  }, 2000);
});

// ---------------------------------------------------------------------------
// AutoApprovalHandler
// ---------------------------------------------------------------------------

describe("AutoApprovalHandler", () => {
  const ctx = { sessionId: "session-auto" };

  it("allows a tool in the allow list", async () => {
    const handler = new AutoApprovalHandler({ allow: ["safe_tool"], deny: [] });
    const decision = await handler.request(makeCall({ name: "safe_tool" }), ctx);
    expect(decision.granted).toBe(true);
  });

  it("denies a tool in the deny list (deny takes precedence)", async () => {
    const handler = new AutoApprovalHandler({
      allow: ["safe_tool"],
      deny: ["safe_tool"],
    });
    const decision = await handler.request(makeCall({ name: "safe_tool" }), ctx);
    expect(decision.granted).toBe(false);
    expect(decision.reason).toContain("deny list");
  });

  it("denies an unknown tool when allowAll is false (default)", async () => {
    const handler = new AutoApprovalHandler({ allow: [], deny: [] });
    const decision = await handler.request(makeCall({ name: "unknown_tool" }), ctx);
    expect(decision.granted).toBe(false);
  });

  it("allowAll:true allows an unknown tool not in deny list", async () => {
    const handler = new AutoApprovalHandler({ allow: [], deny: [], allowAll: true });
    const decision = await handler.request(makeCall({ name: "unknown_tool" }), ctx);
    expect(decision.granted).toBe(true);
  });

  it("allowAll:true still denies tools in the deny list", async () => {
    const handler = new AutoApprovalHandler({
      allow: [],
      deny: ["bad_tool"],
      allowAll: true,
    });
    const decision = await handler.request(makeCall({ name: "bad_tool" }), ctx);
    expect(decision.granted).toBe(false);
  });
});
