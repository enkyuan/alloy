/**
 * Approval handler that communicates via the EventStore.
 *
 * On `request`:
 * 1. Appends `TOOL_APPROVAL_REQUESTED` to the store so external systems can
 *    observe and act on it (e.g. a UI, Slack bot, or another service).
 * 2. Subscribes to the store for the session and races incoming events
 *    against a configurable timeout (default 30 s).
 * 3. Resolves with `{ granted: true }` on `TOOL_APPROVAL_APPROVED` or
 *    `{ granted: false, reason }` on `TOOL_APPROVAL_REJECTED` — both matched
 *    by `tool_call_id`.
 * 4. Rejects with a timeout error if no decision arrives in time.
 */
import type { ToolCall } from "../../providers/base";
import type { EventStore } from "../../events/store";
import { KajiEvent } from "../../events/schemas";
import { EventType } from "../../events/types";
import type { TypedApprovalHandler, ToolContext, ApprovalDecision } from "./types";

const DEFAULT_TIMEOUT_MS = 30_000;

export class EventApprovalHandler implements TypedApprovalHandler {
  constructor(
    private readonly store: EventStore,
    private readonly opts: { timeoutMs?: number } = {},
  ) {}

  async request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision> {
    const timeoutMs = this.opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    await this.store.append(
      KajiEvent.parse({
        type: EventType.TOOL_APPROVAL_REQUESTED,
        session_id: ctx.sessionId,
        tool_name: call.name,
        tool_call_id: call.id,
        tool_args: call.args,
        risk: ctx.risk ?? null,
      }),
    );

    return new Promise<ApprovalDecision>((resolve, reject) => {
      let settled = false;

      const unsubscribe = this.store.subscribe(ctx.sessionId, (event) => {
        if (settled) return;

        if (event.type === EventType.TOOL_APPROVAL_APPROVED && event.tool_call_id === call.id) {
          settled = true;
          unsubscribe();
          clearTimeout(timer);
          resolve({ granted: true });
          return;
        }

        if (event.type === EventType.TOOL_APPROVAL_REJECTED && event.tool_call_id === call.id) {
          settled = true;
          unsubscribe();
          clearTimeout(timer);
          resolve({ granted: false, reason: event.reason ?? undefined });
        }
      });

      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        unsubscribe();
        reject(new Error(`Tool approval timed out after ${timeoutMs}ms`));
      }, timeoutMs);
    });
  }
}
