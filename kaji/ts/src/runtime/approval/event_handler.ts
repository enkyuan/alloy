/**
 * Approval handler that communicates via the EventStore.
 *
 * On `request`:
 * 1. Subscribes to the store for the session.
 * 2. Appends `TOOL_APPROVAL_REQUESTED` to the store so external systems can
 *    observe and act on it (e.g. a UI, Slack bot, or another service).
 * 3. Races incoming events
 *    against a configurable timeout (default 30 s).
 * 4. Resolves with `{ granted: true }` on `TOOL_APPROVAL_APPROVED` or
 *    `{ granted: false, reason }` on `TOOL_APPROVAL_REJECTED` — both matched
 *    by `tool_call_id`.
 * 5. Rejects with a timeout error if no decision arrives in time.
 */
import type { ToolCall } from "@/providers/base";
import type { EventStore } from "@/events/store";
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import type { TypedApprovalHandler, ToolContext, ApprovalDecision } from "@/runtime/approval/types";

const DEFAULT_TIMEOUT_MS = 30_000;

export class EventApprovalHandler implements TypedApprovalHandler {
  readonly emitsApprovalRequest = true;

  constructor(
    private readonly store: EventStore,
    private readonly opts: { timeoutMs?: number } = {},
  ) {}

  async request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision> {
    const timeoutMs = this.opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    return new Promise<ApprovalDecision>((resolve, reject) => {
      let settled = false;
      let unsubscribe: () => void = () => {};
      let timer: ReturnType<typeof setTimeout>;

      const finish = (decision: ApprovalDecision): void => {
        if (settled) return;
        settled = true;
        unsubscribe();
        clearTimeout(timer);
        resolve(decision);
      };

      unsubscribe = this.store.subscribe(ctx.sessionId, (event) => {
        if (event.type === EventType.TOOL_APPROVAL_APPROVED && event.tool_call_id === call.id) {
          finish({ granted: true });
          return;
        }

        if (event.type === EventType.TOOL_APPROVAL_REJECTED && event.tool_call_id === call.id) {
          finish({ granted: false, reason: event.reason ?? undefined });
        }
      });

      timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        unsubscribe();
        reject(new Error(`Tool approval timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      void this.store
        .append(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REQUESTED,
            session_id: ctx.sessionId,
            tool_name: call.name,
            tool_call_id: call.id,
            tool_args: call.args,
            risk: ctx.risk ?? null,
          }),
        )
        .catch((error) => {
          if (settled) return;
          settled = true;
          unsubscribe();
          clearTimeout(timer);
          reject(error);
        });
    });
  }
}
