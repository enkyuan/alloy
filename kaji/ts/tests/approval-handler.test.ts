import { describe, expect, it, vi } from "vitest";

import { InMemoryEventCommitter } from "@/events/committer";
import type { EventCommitter } from "@/events/protocols";
import { KajiEvent, type StoredKajiEvent } from "@/events/schemas";
import { InMemoryEventStore } from "@/events/store";
import { EventType } from "@/events/types";
import type { ToolCall } from "@/providers/base";
import { AutoApprovalHandler } from "@/runtime/approval/auto";
import { EventApprovalHandler } from "@/runtime/approval/handler";
import { adaptLegacyApprovalHandler, type ApprovalRequestContext } from "@/runtime/approval/types";
import { replaySession } from "@/sessions/replay";
import { systemTimerScheduler } from "@/internal/uuid";

class MalformedReadStore extends InMemoryEventStore {
  constructor(private readonly missingField: string) {
    super();
  }

  override async getEvents(
    sessionId: string,
    options: { afterSequence?: number; limit?: number } = {},
  ): Promise<StoredKajiEvent[]> {
    const events = await super.getEvents(sessionId, options);
    return events.map((event) => {
      const row = structuredClone(event) as Record<string, unknown>;
      delete row[this.missingField];
      return row as unknown as StoredKajiEvent;
    });
  }
}

function makeCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return { id: "call-1", name: "my_tool", args: {}, ...overrides };
}

function makeContext(
  committer: EventCommitter,
  call: ToolCall,
  options: {
    controller?: AbortController;
    sessionId?: string;
    turnId?: string;
    deadlineMonotonicMs?: number;
    emit?: ApprovalRequestContext["emit"];
  } = {},
): ApprovalRequestContext {
  const controller = options.controller ?? new AbortController();
  const sessionId = options.sessionId ?? "session-1";
  const turnId = options.turnId ?? "turn-1";
  return {
    execution: {
      principalId: "principal-1",
      sessionId,
      turnId,
      requestId: "request-1",
      traceId: "trace-1",
      toolCallId: call.id,
      idempotencyKey: `${sessionId}:${call.id}`,
      signal: controller.signal,
      metadata: {},
    },
    toolName: call.name,
    risk: "write",
    arguments: structuredClone(call.args),
    committer,
    emit:
      options.emit ??
      (async (event) => {
        return committer.commit(event);
      }),
    deadlineMonotonicMs: options.deadlineMonotonicMs ?? globalThis.performance.now() + 1_000,
    deadlineSource: "approval",
    timerScheduler: systemTimerScheduler,
  };
}

async function decideAfterRequest(
  committer: EventCommitter,
  context: ApprovalRequestContext,
  call: ToolCall,
  decision: "approved" | "rejected",
): Promise<void> {
  const events = committer.subscribe(context.execution.sessionId);
  try {
    for await (const event of events) {
      if (
        event.type === EventType.TOOL_APPROVAL_REQUESTED &&
        event.turn_id === context.execution.turnId &&
        event.tool_call_id === call.id &&
        event.tool_name === call.name
      ) {
        await committer.commit(
          KajiEvent.parse({
            type:
              decision === "approved"
                ? EventType.TOOL_APPROVAL_APPROVED
                : EventType.TOOL_APPROVAL_REJECTED,
            session_id: context.execution.sessionId,
            turn_id: context.execution.turnId,
            tool_name: call.name,
            tool_call_id: call.id,
            ...(decision === "rejected"
              ? { error_code: "APPROVAL_REJECTED", reason: "Not authorized" }
              : {}),
          }),
        );
        return;
      }
    }
  } finally {
    await events.return?.();
  }
}

describe("EventApprovalHandler", () => {
  it.each(["id", "version", "timestamp"])(
    "canonically validates persisted requests missing %s before correlation",
    async (missingField) => {
      const store = new MalformedReadStore(missingField);
      const committer = new InMemoryEventCommitter(store);
      const call = makeCall({ id: `malformed-${missingField}` });
      const context = makeContext(committer, call, {
        sessionId: `malformed-${missingField}`,
      });

      await expect(new EventApprovalHandler().request(call, context)).rejects.toMatchObject({
        code: "EVENT_SCHEMA_INCOMPATIBLE",
        path: `/${missingField}`,
      });
      expect(await store.lastSequence(context.execution.sessionId)).toBe(1);
    },
  );

  it("subscribes before using the runtime emitter and returns recorded approval", async () => {
    const inner = new InMemoryEventCommitter(new InMemoryEventStore());
    let subscribed = false;
    const committer: EventCommitter = {
      store: inner.store,
      commit: (event) => inner.commit(event),
      subscribe(sessionId, options) {
        subscribed = true;
        return inner.subscribe(sessionId, options);
      },
    };
    const call = makeCall({ id: "call-approved" });
    const context = makeContext(committer, call, {
      emit: async (event) => {
        expect(subscribed).toBe(true);
        return committer.commit(event);
      },
    });
    const bridge = decideAfterRequest(committer, context, call, "approved");

    await expect(new EventApprovalHandler().request(call, context)).resolves.toEqual({
      granted: true,
      code: "approved",
      recorded: true,
    });
    await bridge;
  });

  it("returns a recorded rejection with the stable external code", async () => {
    const committer = new InMemoryEventCommitter(new InMemoryEventStore());
    const call = makeCall({ id: "call-rejected" });
    const context = makeContext(committer, call);
    const bridge = decideAfterRequest(committer, context, call, "rejected");

    await expect(new EventApprovalHandler().request(call, context)).resolves.toEqual({
      granted: false,
      code: "rejected",
      reason: "Not authorized",
      recorded: true,
    });
    await bridge;
  });

  it("returns typed timeout and caller cancellation decisions", async () => {
    const committer = new InMemoryEventCommitter(new InMemoryEventStore());
    const timeoutCall = makeCall({ id: "call-timeout" });
    await expect(
      new EventApprovalHandler().request(
        timeoutCall,
        makeContext(committer, timeoutCall, {
          deadlineMonotonicMs: globalThis.performance.now() + 10,
        }),
      ),
    ).resolves.toMatchObject({ granted: false, code: "timeout" });

    const controller = new AbortController();
    const cancelledCall = makeCall({ id: "call-cancelled" });
    const pending = new EventApprovalHandler().request(
      cancelledCall,
      makeContext(committer, cancelledCall, {
        controller,
        sessionId: "session-cancelled",
        deadlineMonotonicMs: globalThis.performance.now() + 1_000,
      }),
    );
    controller.abort();
    await expect(pending).resolves.toMatchObject({ granted: false, code: "cancelled" });
  });

  it("ignores stale decisions and all wrong tri-key components", async () => {
    const committer = new InMemoryEventCommitter(new InMemoryEventStore());
    const call = makeCall({ id: "reused-call", name: "target" });
    const context = makeContext(committer, call, {
      sessionId: "session-trikey",
      turnId: "current-turn",
    });
    for (const candidate of [
      { turnId: "stale-turn", callId: call.id, name: call.name },
      { turnId: context.execution.turnId, callId: "wrong-call", name: call.name },
      { turnId: context.execution.turnId, callId: call.id, name: "wrong-tool" },
    ]) {
      await committer.commit(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_APPROVED,
          session_id: context.execution.sessionId,
          turn_id: candidate.turnId,
          tool_name: candidate.name,
          tool_call_id: candidate.callId,
        }),
      );
    }
    const bridge = decideAfterRequest(committer, context, call, "approved");
    await expect(new EventApprovalHandler().request(call, context)).resolves.toMatchObject({
      granted: true,
      recorded: true,
    });
    await bridge;
  });

  it("ignores a matching decision before the exact request sequence and closes replay", async () => {
    const inner = new InMemoryEventCommitter(new InMemoryEventStore());
    const returned = vi.fn();
    const committer: EventCommitter = {
      store: inner.store,
      commit: (event) => inner.commit(event),
      subscribe(sessionId, options) {
        const iterator = inner.subscribe(sessionId, options);
        const originalReturn = iterator.return?.bind(iterator);
        iterator.return = async () => {
          returned();
          return originalReturn?.() ?? { value: undefined, done: true };
        };
        return iterator;
      },
    };
    const call = makeCall({ id: "raced-call", name: "ship" });
    const context = makeContext(committer, call, {
      sessionId: "raced-session",
      turnId: "raced-turn",
      emit: async (request) => {
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_APPROVED,
            session_id: "raced-session",
            turn_id: "raced-turn",
            tool_name: "ship",
            tool_call_id: "raced-call",
          }),
        );
        const storedRequest = await committer.commit(request);
        await committer.commit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REJECTED,
            session_id: "raced-session",
            turn_id: "raced-turn",
            tool_name: "ship",
            tool_call_id: "raced-call",
            error_code: "APPROVAL_REJECTED",
            reason: "Post-request decision",
          }),
        );
        return storedRequest;
      },
    });

    await expect(new EventApprovalHandler().request(call, context)).resolves.toEqual({
      granted: false,
      code: "rejected",
      reason: "Post-request decision",
      recorded: true,
    });
    const events = await inner.store.getEvents("raced-session");
    expect(events.map(({ sequence }) => sequence)).toEqual([1, 2, 3]);
    expect(replaySession(events).pendingApprovals.size).toBe(0);
    expect(returned).toHaveBeenCalledOnce();
  });

  it("rejects a request returned from a different committer journal", async () => {
    const approvalCommitter = new InMemoryEventCommitter(new InMemoryEventStore());
    const emitStore = new InMemoryEventStore();
    const emitCommitter = new InMemoryEventCommitter(emitStore);
    const call = makeCall({ id: "wrong-journal" });
    const context = makeContext(approvalCommitter, call, {
      sessionId: "wrong-journal-session",
      emit: (event) => emitCommitter.commit(event),
    });

    await expect(new EventApprovalHandler().request(call, context)).rejects.toThrow(
      /not stored by the approval committer/i,
    );
    expect(await approvalCommitter.store.getEvents("wrong-journal-session")).toEqual([]);
    expect(await emitStore.getEvents("wrong-journal-session")).toHaveLength(1);
  });

  it("closes the subscription after every terminal outcome", async () => {
    const inner = new InMemoryEventCommitter(new InMemoryEventStore());
    const returned = vi.fn();
    const committer: EventCommitter = {
      store: inner.store,
      commit: (event) => inner.commit(event),
      subscribe(sessionId, options) {
        const iterator = inner.subscribe(sessionId, options);
        const originalReturn = iterator.return?.bind(iterator);
        iterator.return = async () => {
          returned();
          return originalReturn?.() ?? { value: undefined, done: true };
        };
        return iterator;
      },
    };
    const call = makeCall({ id: "cleanup" });
    await new EventApprovalHandler().request(
      call,
      makeContext(committer, call, {
        deadlineMonotonicMs: globalThis.performance.now() + 5,
      }),
    );
    expect(returned).toHaveBeenCalledOnce();
  });

  it("does not hang on a non-cooperative custom iterator return", async () => {
    const store = new InMemoryEventStore();
    const returned = vi.fn();
    const committer: EventCommitter = {
      store,
      commit: async (event) => (await store.append(event)).event,
      subscribe() {
        return {
          next: () => new Promise<IteratorResult<never>>(() => {}),
          return: () => {
            returned();
            return new Promise<IteratorResult<never>>(() => {});
          },
          [Symbol.asyncIterator]() {
            return this;
          },
        };
      },
    };
    const call = makeCall({ id: "non-cooperative" });
    const decision = await Promise.race([
      new EventApprovalHandler().request(
        call,
        makeContext(committer, call, {
          deadlineMonotonicMs: globalThis.performance.now() + 5,
        }),
      ),
      new Promise<never>((_resolve, reject) =>
        setTimeout(() => reject(new Error("approval cleanup hung")), 100),
      ),
    ]);
    expect(decision).toMatchObject({ granted: false, code: "timeout" });
    expect(returned).toHaveBeenCalledOnce();
  });

  it("isolates Boolean callbacks behind the deprecated compatibility adapter", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {
      throw new Error("console unavailable");
    });
    const handler = vi.fn().mockResolvedValue(true);
    const call = makeCall({ name: "legacy" });
    const committer = new InMemoryEventCommitter(new InMemoryEventStore());
    try {
      await expect(
        adaptLegacyApprovalHandler(handler).request(call, makeContext(committer, call)),
      ).resolves.toEqual({ granted: true, code: "approved" });
      expect(handler).toHaveBeenCalledOnce();
    } finally {
      warning.mockRestore();
    }
  });
});

describe("AutoApprovalHandler", () => {
  const committer = new InMemoryEventCommitter(new InMemoryEventStore());

  it("uses the typed approved/rejected union", async () => {
    const allow = new AutoApprovalHandler({ allow: ["safe"], deny: [] });
    const allowed = makeCall({ id: "allow", name: "safe" });
    await expect(allow.request(allowed, makeContext(committer, allowed))).resolves.toEqual({
      granted: true,
      code: "approved",
    });

    const deny = new AutoApprovalHandler({ allow: [], deny: ["unsafe"] });
    const denied = makeCall({ id: "deny", name: "unsafe" });
    await expect(deny.request(denied, makeContext(committer, denied))).resolves.toMatchObject({
      granted: false,
      code: "rejected",
    });
  });
});
