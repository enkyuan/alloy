import { describe, expect, it, vi } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import { KajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import { AgentRuntime } from "@/runtime/runtime";
import { MockProvider } from "@/providers/mock";
import { approvalKey, replaySession } from "@/sessions/replay";
import { ToolPlanner, bindEmitterToCommitter, type AnyApprovalHandler } from "@/tools/planner";
import { ToolPolicy } from "@/tools/policy";

const SPEC = {
  name: "ship",
  description: "ship",
  parameters: {},
  risk: "write" as const,
};

async function executeApproval(
  handler: AnyApprovalHandler | undefined,
  options: {
    deadlineMs?: number;
    onEvent?: (type: string) => void;
    controller?: AbortController;
  } = {},
) {
  const store = new InMemoryEventStore();
  const committer = new InMemoryEventCommitter(store);
  const executor = vi.fn().mockResolvedValue({ ok: true });
  const planner = new ToolPlanner({
    executor,
    policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
    approvalHandler: handler,
    approvalCommitter: committer,
    executionLimits: { approvalTimeoutMs: 10 },
    specs: new Map([[SPEC.name, SPEC]]),
  });
  const controller = options.controller ?? new AbortController();
  const results = await planner.executeBatch(
    "session",
    [{ id: "call", name: SPEC.name, arguments: {} }],
    bindEmitterToCommitter(async (event) => {
      const stored = await committer.commit(event);
      options.onEvent?.(event.type);
      return stored;
    }, committer),
    "turn",
    {
      principalId: "principal",
      requestId: "request",
      traceId: "trace",
      ...(options.deadlineMs === undefined ? {} : { deadlineMs: options.deadlineMs }),
    },
    controller.signal,
  );
  return { store, executor, results };
}

describe("approval lifecycle closure", () => {
  it("records the exact timeout sequence and leaves replay closed", async () => {
    const { store, executor, results } = await executeApproval(new EventApprovalHandler());
    const events = await store.getEvents("session");

    expect(events.map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_REJECTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(events[2]).toMatchObject({
      error_code: "APPROVAL_TIMEOUT",
      reason: "Tool approval timed out",
    });
    expect(events[3]).toMatchObject({
      error_code: "APPROVAL_TIMEOUT",
      retryable: true,
      outcome: "not_started",
    });
    expect(results[0]).toMatchObject({
      error_code: "APPROVAL_TIMEOUT",
      retryable: true,
      outcome: "not_started",
    });
    expect(executor).not.toHaveBeenCalled();
    expect(events).not.toContainEqual(
      expect.objectContaining({ type: EventType.TOOL_CALL_STARTED }),
    );
    expect(replaySession(events).pendingApprovals.size).toBe(0);
  });

  it.each([
    [
      "rejected",
      {
        request: async () => ({
          granted: false as const,
          code: "rejected" as const,
          reason: "Operator rejected",
        }),
      },
      "APPROVAL_REJECTED",
      false,
    ],
    ["missing", undefined, "APPROVAL_UNAVAILABLE", false],
    [
      "handler failure",
      {
        request: async () => {
          throw new Error("private approval bridge failure");
        },
      },
      "APPROVAL_UNAVAILABLE",
      false,
    ],
  ])("closes %s with one stable terminal", async (_name, handler, code, retryable) => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const { store, executor, results } = await executeApproval(handler);
    const events = await store.getEvents("session");
    expect(events.filter((event) => event.type === EventType.TOOL_CALL_FAILED)).toHaveLength(1);
    expect(events.filter((event) => event.type === EventType.TOOL_APPROVAL_REJECTED)).toHaveLength(
      1,
    );
    expect(results[0]).toMatchObject({ error_code: code, retryable, outcome: "not_started" });
    expect(executor).not.toHaveBeenCalled();
    expect(replaySession(events).pendingApprovals.size).toBe(0);
    log.mockRestore();
  });

  it("does not duplicate an externally recorded rejection", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const handler = new EventApprovalHandler();
    const observer = committer.subscribe("session");
    const bridge = (async () => {
      for await (const event of observer) {
        if (event.type !== EventType.TOOL_APPROVAL_REQUESTED) continue;
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REJECTED,
            session_id: "session",
            turn_id: "turn",
            tool_name: "ship",
            tool_call_id: "call",
            error_code: "APPROVAL_REJECTED",
            reason: "External rejection",
          }),
        );
        return;
      }
    })();
    const executor = vi.fn();
    const planner = new ToolPlanner({
      executor,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
      approvalHandler: handler,
      approvalCommitter: committer,
      specs: new Map([[SPEC.name, SPEC]]),
    });

    await planner.executeBatch(
      "session",
      [{ id: "call", name: "ship", arguments: {} }],
      ToolPlanner.committerEmitter(committer),
      "turn",
      { principalId: "principal", requestId: "request", traceId: "trace" },
    );
    await bridge;
    const events = await store.getEvents("session");
    expect(events.filter((event) => event.type === EventType.TOOL_APPROVAL_REJECTED)).toHaveLength(
      1,
    );
    expect(events.filter((event) => event.type === EventType.TOOL_CALL_FAILED)).toHaveLength(1);
    expect(replaySession(events).rejectedApprovals.get(approvalKey("turn", "call", "ship"))).toBe(
      "APPROVAL_REJECTED",
    );
  });

  it("maps an already-expired turn deadline to approval timeout", async () => {
    const { results } = await executeApproval(new EventApprovalHandler(), {
      deadlineMs: Date.now() - 1,
    });
    expect(results[0]).toMatchObject({ error_code: "APPROVAL_TIMEOUT", outcome: "not_started" });
  });

  it("rejects a standalone emitter bound to a different approval committer", async () => {
    const approvalStore = new InMemoryEventStore();
    const approvalCommitter = new InMemoryEventCommitter(approvalStore);
    const emitStore = new InMemoryEventStore();
    const emitCommitter = new InMemoryEventCommitter(emitStore);
    const executor = vi.fn();
    const planner = new ToolPlanner({
      executor,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
      approvalHandler: new EventApprovalHandler(),
      approvalCommitter,
      specs: new Map([[SPEC.name, SPEC]]),
    });

    await expect(
      planner.executeBatch(
        "mismatched-session",
        [{ id: "mismatched-call", name: "ship", arguments: {} }],
        ToolPlanner.committerEmitter(emitCommitter),
        "mismatched-turn",
        { principalId: "principal", requestId: "request", traceId: "trace" },
      ),
    ).rejects.toThrow(/emitter committer must match/i);
    expect(executor).not.toHaveBeenCalled();
    expect(await approvalStore.getEvents("mismatched-session")).toEqual([]);
    expect(await emitStore.getEvents("mismatched-session")).toEqual([]);
  });

  it("closes caller cancellation before the executor starts", async () => {
    const controller = new AbortController();
    const { store, executor, results } = await executeApproval(new EventApprovalHandler(), {
      controller,
      onEvent: (type) => {
        if (type === EventType.TOOL_APPROVAL_REQUESTED) controller.abort();
      },
    });
    expect(results[0]).toMatchObject({
      error_code: "TOOL_CANCELLED",
      retryable: true,
      outcome: "not_started",
    });
    expect(executor).not.toHaveBeenCalled();
    expect((await store.getEvents("session")).map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_REJECTED,
      EventType.TOOL_CALL_FAILED,
    ]);
  });

  it("uses an earlier durable approval over local cancellation without clearing abort", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const controller = new AbortController();
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const planner = new ToolPlanner({
      executor,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
      approvalHandler: new EventApprovalHandler(),
      approvalCommitter: committer,
      specs: new Map([[SPEC.name, SPEC]]),
    });
    const emit = bindEmitterToCommitter(async (event) => {
      if (
        event.type === EventType.TOOL_APPROVAL_REJECTED &&
        event.error_code === "TOOL_CANCELLED"
      ) {
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: "cancel-race",
            turn_id: "turn",
            tool_name: "ship",
            tool_call_id: "call",
          }),
        );
      }
      const stored = await committer.commit(event);
      if (event.type === EventType.TOOL_APPROVAL_REQUESTED) controller.abort();
      return stored;
    }, committer);

    const results = await planner.executeBatch(
      "cancel-race",
      [{ id: "call", name: "ship", arguments: {} }],
      emit,
      "turn",
      { principalId: "principal", requestId: "request", traceId: "trace" },
      controller.signal,
    );
    const events = await store.getEvents("cancel-race");
    const approvalEvents = events.filter((event) =>
      [
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_APPROVED,
        EventType.TOOL_APPROVAL_REJECTED,
      ].includes(event.type as never),
    );
    expect(approvalEvents.map(({ type }) => type)).toEqual([
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_APPROVED,
      EventType.TOOL_APPROVAL_REJECTED,
    ]);
    const replayed = replaySession(events);
    expect(replayed.approvedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(true);
    expect(replayed.rejectedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(false);
    expect(results[0]).toMatchObject({ error_code: "TOOL_CANCELLED", outcome: "not_started" });
    expect(String("error_code" in results[0]! ? results[0].error_code : "")).not.toMatch(
      /^APPROVAL_/,
    );
    expect(events.at(-1)).toMatchObject({
      type: EventType.TOOL_CALL_FAILED,
      error_code: "TOOL_CANCELLED",
      outcome: "not_started",
    });
    expect(executor).not.toHaveBeenCalled();
  });

  it("uses an earlier durable approval over a local approval timeout", async () => {
    vi.useFakeTimers();
    try {
      const store = new InMemoryEventStore();
      const committer = new InMemoryEventCommitter(store);
      const executor = vi.fn().mockResolvedValue({ ok: true });
      const planner = new ToolPlanner({
        executor,
        policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
        approvalHandler: { request: () => new Promise(() => {}) },
        approvalCommitter: committer,
        executionLimits: { approvalTimeoutMs: 50 },
        specs: new Map([[SPEC.name, SPEC]]),
      });
      let sawRequest!: () => void;
      const requestRecorded = new Promise<void>((resolve) => {
        sawRequest = resolve;
      });
      const emit = bindEmitterToCommitter(async (event) => {
        if (
          event.type === EventType.TOOL_APPROVAL_REJECTED &&
          event.error_code === "APPROVAL_TIMEOUT"
        ) {
          await committer.commit(
            KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_APPROVED,
              session_id: "timeout-race",
              turn_id: "turn",
              tool_name: "ship",
              tool_call_id: "call",
            }),
          );
        }
        const stored = await committer.commit(event);
        if (event.type === EventType.TOOL_APPROVAL_REQUESTED) sawRequest();
        return stored;
      }, committer);

      const pending = planner.executeBatch(
        "timeout-race",
        [{ id: "call", name: "ship", arguments: {} }],
        emit,
        "turn",
        { principalId: "principal", requestId: "request", traceId: "trace" },
      );
      await requestRecorded;
      await vi.advanceTimersByTimeAsync(50);
      const results = await pending;
      const events = await store.getEvents("timeout-race");
      expect(
        events.filter((event) => event.type.startsWith("tool.approval.")).map(({ type }) => type),
      ).toEqual([
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_APPROVED,
        EventType.TOOL_APPROVAL_REJECTED,
      ]);
      const replayed = replaySession(events);
      expect(replayed.approvedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(true);
      expect(replayed.rejectedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(false);
      expect(results[0]).toMatchObject({ result: { ok: true } });
      expect(events.at(-1)).toMatchObject({ type: EventType.TOOL_CALL_COMPLETED });
      expect(events.some((event) => event.type === EventType.TOOL_CALL_FAILED)).toBe(false);
      expect(executor).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses an observed durable approval over an opposite unrecorded handler return", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const observer = committer.subscribe("opposite-return");
    const bridge = (async () => {
      for await (const event of observer) {
        if (event.type !== EventType.TOOL_APPROVAL_REQUESTED) continue;
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: "opposite-return",
            turn_id: "turn",
            tool_name: "ship",
            tool_call_id: "call",
          }),
        );
        return;
      }
    })();
    const eventHandler = new EventApprovalHandler();
    const handler = {
      approvalRequestOwner: "handler" as const,
      async request(...args: Parameters<EventApprovalHandler["request"]>) {
        const observed = await eventHandler.request(...args);
        expect(observed).toMatchObject({ granted: true, recorded: true });
        return {
          granted: false as const,
          code: "cancelled" as const,
          reason: "Opposite local return",
        };
      },
    };
    const executor = vi.fn().mockResolvedValue({ ok: true });
    const planner = new ToolPlanner({
      executor,
      policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
      approvalHandler: handler,
      approvalCommitter: committer,
      specs: new Map([[SPEC.name, SPEC]]),
    });

    const results = await planner.executeBatch(
      "opposite-return",
      [{ id: "call", name: "ship", arguments: {} }],
      ToolPlanner.committerEmitter(committer),
      "turn",
      { principalId: "principal", requestId: "request", traceId: "trace" },
    );
    await bridge;
    const events = await store.getEvents("opposite-return");
    expect(
      events.filter((event) => event.type.startsWith("tool.approval.")).map(({ type }) => type),
    ).toEqual([
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_APPROVED,
      EventType.TOOL_APPROVAL_REJECTED,
    ]);
    const replayed = replaySession(events);
    expect(replayed.approvedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(true);
    expect(replayed.rejectedApprovals.has(approvalKey("turn", "call", "ship"))).toBe(false);
    expect(results[0]).toMatchObject({ result: { ok: true } });
    expect(events.at(-1)).toMatchObject({ type: EventType.TOOL_CALL_COMPLETED });
    expect(executor).toHaveBeenCalledOnce();
  });

  it("backfills the request before closing a broken event-backed handler", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const { store } = await executeApproval({
      approvalRequestOwner: "handler" as const,
      request: async () => {
        throw new Error("bridge failed before emit");
      },
    });
    expect((await store.getEvents("session")).map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_REJECTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    log.mockRestore();
  });

  it("does not trust an event-backed decision returned without its request event", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const { store, executor, results } = await executeApproval({
      approvalRequestOwner: "handler" as const,
      request: async () => ({ granted: true, code: "approved" }),
    });
    expect((await store.getEvents("session")).map((event) => event.type)).toEqual([
      EventType.TOOL_CALL_REQUESTED,
      EventType.TOOL_APPROVAL_REQUESTED,
      EventType.TOOL_APPROVAL_REJECTED,
      EventType.TOOL_CALL_FAILED,
    ]);
    expect(results[0]).toMatchObject({ error_code: "APPROVAL_UNAVAILABLE" });
    expect(executor).not.toHaveBeenCalled();
    log.mockRestore();
  });

  it("fails closed when the handler marker and diagnostic console both throw", async () => {
    const request = vi.fn();
    const handler = {
      get approvalRequestOwner(): "handler" {
        throw new Error("unsafe marker getter");
      },
      request,
    };
    const log = vi.spyOn(console, "error").mockImplementation(() => {
      throw new Error("console unavailable");
    });
    try {
      const { store, executor, results } = await executeApproval(handler);
      expect((await store.getEvents("session")).map((event) => event.type)).toEqual([
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_APPROVAL_REQUESTED,
        EventType.TOOL_APPROVAL_REJECTED,
        EventType.TOOL_CALL_FAILED,
      ]);
      expect(results[0]).toMatchObject({
        error_code: "APPROVAL_UNAVAILABLE",
        outcome: "not_started",
      });
      expect(request).not.toHaveBeenCalled();
      expect(executor).not.toHaveBeenCalled();
    } finally {
      log.mockRestore();
    }
  });

  it("includes externally committed approval decisions in turn events in sequence order", async () => {
    const store = new InMemoryEventStore();
    const committer = new InMemoryEventCommitter(store);
    const sessionId = "turn-external-approval";
    const observer = committer.subscribe(sessionId);
    const bridge = (async () => {
      for await (const event of observer) {
        if (event.type !== EventType.TOOL_APPROVAL_REQUESTED) continue;
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: sessionId,
            turn_id: event.turn_id,
            tool_name: event.tool_name,
            tool_call_id: event.tool_call_id,
          }),
        );
        return;
      }
    })();
    const runtime = new AgentRuntime({
      provider: new MockProvider({ toolCall: { name: "ship", args: {} } }),
      store,
      committer,
      tools: [SPEC],
      policy: new ToolPolicy({ requireApprovalFor: new Set(["write"]) }),
      approvalHandler: new EventApprovalHandler(),
      toolExecutor: async () => ({ ok: true }),
      defaultContext: { principalId: "principal" },
    });

    const result = await runtime.turn("ship it", { sessionId });
    await bridge;
    const persisted = await store.getEvents(sessionId);
    expect(result.events.map(({ id }) => id)).toEqual(persisted.map(({ id }) => id));
    expect(result.events.map(({ sequence }) => sequence)).toEqual(
      Array.from({ length: result.events.length }, (_, index) => index + 1),
    );
    expect(result.events.map(({ type }) => type)).toContain(EventType.TOOL_APPROVAL_APPROVED);
  });

  it.each(["", "x".repeat(201)])(
    "treats malformed rejection reason length %s as unavailable",
    async (reason) => {
      const log = vi.spyOn(console, "error").mockImplementation(() => {});
      const { store, results } = await executeApproval({
        request: async () => ({
          granted: false,
          code: "rejected",
          reason,
        }),
      });
      const events = await store.getEvents("session");
      expect(events[1]).toMatchObject({ type: EventType.TOOL_APPROVAL_REQUESTED });
      expect(events[2]).toMatchObject({
        type: EventType.TOOL_APPROVAL_REJECTED,
        error_code: "APPROVAL_UNAVAILABLE",
        reason: "Approval handler unavailable",
      });
      expect(results[0]).toMatchObject({ error_code: "APPROVAL_UNAVAILABLE" });
      log.mockRestore();
    },
  );
});
