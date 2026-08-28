/** Event-backed approval waiter using the runtime's canonical committer/emitter. */
import { KajiEvent, StoredKajiEvent, validateStoredEvent } from "@/events/schemas";
import { structurallyEqualJson } from "@/events/json";
import { EventType } from "@/events/types";
import type { ToolCall } from "@/providers/base";
import type {
  ApprovalDecision,
  ApprovalRejectionCode,
  ApprovalRequestContext,
  EventBackedApprovalHandler,
} from "@/runtime/approval/types";
import { snapshotToolExecutionContext } from "@/runtime/context";
import {
  systemClock,
  systemIdFactory,
  type Clock,
  type IdFactory,
  type TimerHandle,
} from "@/internal/uuid";

function decisionCode(errorCode: string): ApprovalRejectionCode {
  if (errorCode === "TURN_TIMEOUT") return "turn_timeout";
  if (errorCode === "APPROVAL_TIMEOUT") return "timeout";
  if (errorCode === "TOOL_CANCELLED") return "cancelled";
  if (errorCode === "APPROVAL_UNAVAILABLE") return "unavailable";
  return "rejected";
}

export interface EventApprovalHandlerOptions {
  /** Monotonic clock source for approval deadlines. */
  now?: () => number;
  idFactory?: IdFactory;
  clock?: Clock;
}

export class EventApprovalHandler implements EventBackedApprovalHandler {
  readonly approvalRequestOwner = "handler" as const;
  private readonly now: () => number;
  private readonly idFactory: IdFactory;
  private readonly clock: Clock;

  constructor(options: EventApprovalHandlerOptions = {}) {
    this.idFactory = options.idFactory ?? systemIdFactory;
    this.clock = options.clock ?? systemClock;
    this.now = options.now ?? (() => this.clock.nowMonotonic());
  }

  async request(call: ToolCall, context: ApprovalRequestContext): Promise<ApprovalDecision> {
    const execution = snapshotToolExecutionContext(context.execution);
    if (
      execution.sessionId.length === 0 ||
      execution.turnId.length === 0 ||
      call.id !== execution.toolCallId ||
      call.name !== context.toolName ||
      JSON.stringify(call.args) !== JSON.stringify(context.arguments)
    ) {
      throw new TypeError("Approval context does not match the requested tool call");
    }
    if (!Number.isFinite(context.deadlineMonotonicMs)) {
      throw new TypeError("Approval deadline must be finite");
    }
    const cursor = await context.committer.store.lastSequence(execution.sessionId);
    const events = context.committer.subscribe(execution.sessionId, { afterSequence: cursor });
    let resolveRequestSequence!: (sequence: number) => void;
    const requestSequence = new Promise<number>((resolve) => {
      resolveRequestSequence = resolve;
    });
    let requestSequenceReleased = false;
    const releaseRequestSequence = (sequence: number) => {
      if (requestSequenceReleased) return;
      requestSequenceReleased = true;
      resolveRequestSequence(sequence);
    };

    const externalDecision = (async (): Promise<ApprovalDecision> => {
      while (true) {
        const next = await events.next();
        if (next.done) {
          throw new Error("Approval event stream closed before a decision was recorded");
        }
        const event = next.value;
        const matches =
          event.turn_id === execution.turnId &&
          "tool_call_id" in event &&
          event.tool_call_id === call.id &&
          "tool_name" in event &&
          event.tool_name === call.name;
        if (!matches) continue;
        if (
          event.type !== EventType.TOOL_APPROVAL_APPROVED &&
          event.type !== EventType.TOOL_APPROVAL_REJECTED
        ) {
          continue;
        }
        if (event.sequence <= (await requestSequence)) continue;
        if (event.type === EventType.TOOL_APPROVAL_APPROVED) {
          return { granted: true, code: "approved", recorded: true };
        }
        if (event.type === EventType.TOOL_APPROVAL_REJECTED) {
          return {
            granted: false,
            code: decisionCode(event.error_code),
            reason: event.reason,
            recorded: true,
          };
        }
      }
    })();
    // A timeout/cancellation may win while the iterator is still blocked.
    void externalDecision.catch(() => undefined);

    let timer: TimerHandle | undefined;
    let removeAbortListener = () => {};
    const interrupted = new Promise<ApprovalDecision>((resolve) => {
      let deadlineReached = false;
      let wakeQueued = false;
      const wake = () => {
        if (wakeQueued) return;
        wakeQueued = true;
        queueMicrotask(() => {
          wakeQueued = false;
          if (execution.signal.aborted) {
            resolve({
              granted: false,
              code: "cancelled",
              reason: "Tool approval cancelled",
            });
          } else if (deadlineReached) {
            resolve({
              granted: false,
              code: context.deadlineSource === "turn" ? "turn_timeout" : "timeout",
              reason: "Tool approval timed out",
            });
          }
        });
      };
      const onAbort = () => wake();
      if (execution.signal.aborted) onAbort();
      else {
        execution.signal.addEventListener("abort", onAbort, { once: true });
        removeAbortListener = () => execution.signal.removeEventListener("abort", onAbort);
      }
      timer = context.timerScheduler.schedule(
        Math.max(0, context.deadlineMonotonicMs - (context.nowMonotonic?.() ?? this.now())),
        () => {
          deadlineReached = true;
          wake();
        },
      );
    });

    try {
      const request = KajiEvent.parse({
        id: this.idFactory.next("event"),
        timestamp: this.clock.nowWallSeconds(),
        type: EventType.TOOL_APPROVAL_REQUESTED,
        session_id: execution.sessionId,
        turn_id: execution.turnId,
        tool_name: call.name,
        tool_call_id: call.id,
        tool_args: structuredClone(context.arguments),
        risk: context.risk,
      });
      const stored = StoredKajiEvent.parse(await context.emit(request));
      if (
        stored.id !== request.id ||
        stored.type !== EventType.TOOL_APPROVAL_REQUESTED ||
        stored.session_id !== execution.sessionId ||
        stored.turn_id !== execution.turnId ||
        stored.tool_name !== call.name ||
        stored.tool_call_id !== call.id ||
        stored.sequence <= cursor
      ) {
        throw new TypeError("Approval emitter did not return the stored request event");
      }
      const [canonicalRequest] = (
        await context.committer.store.getEvents(execution.sessionId, {
          afterSequence: stored.sequence - 1,
          limit: 1,
        })
      ).map(validateStoredEvent);
      if (
        canonicalRequest?.id !== stored.id ||
        canonicalRequest.sequence !== stored.sequence ||
        !structurallyEqualJson(canonicalRequest, stored)
      ) {
        throw new TypeError("Approval request was not stored by the approval committer");
      }
      releaseRequestSequence(stored.sequence);
      return await Promise.race([externalDecision, interrupted]);
    } catch (error) {
      releaseRequestSequence(Number.POSITIVE_INFINITY);
      throw error;
    } finally {
      timer?.cancel();
      removeAbortListener();
      // A third-party iterator may implement a non-cooperative return(). Call
      // it exactly once, but never let cleanup hold a completed decision open.
      try {
        const closing = events.return?.();
        if (closing !== undefined) void Promise.resolve(closing).catch(() => undefined);
      } catch {
        // Best-effort iterator cleanup.
      }
    }
  }
}
