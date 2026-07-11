/**
 * Approval handler that communicates through the event committer.
 *
 * On `request`:
 * 1. Subscribes through the committer for the session.
 * 2. Commits `TOOL_APPROVAL_REQUESTED` so external systems can
 *    observe and act on it (e.g. a UI, Slack bot, or another service).
 * 3. Races incoming events
 *    against a configurable timeout (default 30 s).
 * 4. Resolves with `{ granted: true }` on `TOOL_APPROVAL_APPROVED` or
 *    `{ granted: false, reason }` on `TOOL_APPROVAL_REJECTED` — both matched
 *    by `tool_call_id`.
 * 5. Rejects with a timeout error if no decision arrives in time.
 */
import type { ToolCall } from "@/providers/base";
import type { EventCommitter } from "@/events/protocols";
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import type { TypedApprovalHandler, ToolContext, ApprovalDecision } from "@/runtime/approval/types";

const DEFAULT_TIMEOUT_MS = 30_000;

export class EventApprovalHandler implements TypedApprovalHandler {
  readonly emitsApprovalRequest = true;

  constructor(
    private readonly committer: EventCommitter,
    private readonly opts: { timeoutMs?: number } = {},
  ) {}

  async request(call: ToolCall, ctx: ToolContext): Promise<ApprovalDecision> {
    const timeoutMs = this.opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    const events = this.committer.subscribe(ctx.sessionId);
    let cancelDecision: (error: unknown) => void = () => {};
    const decision = new Promise<ApprovalDecision>((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout>;

      const finish = (decision: ApprovalDecision): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(decision);
      };
      cancelDecision = (error: unknown): void => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      };

      void (async () => {
        try {
          for await (const event of events) {
            if (event.type === EventType.TOOL_APPROVAL_APPROVED && event.tool_call_id === call.id) {
              finish({ granted: true });
              return;
            }
            if (event.type === EventType.TOOL_APPROVAL_REJECTED && event.tool_call_id === call.id) {
              finish({ granted: false, reason: event.reason ?? undefined });
              return;
            }
          }
        } catch (error) {
          cancelDecision(error);
        }
      })();

      timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error(`Tool approval timed out after ${timeoutMs}ms`));
      }, timeoutMs);
    });

    try {
      await this.committer.commit(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_REQUESTED,
          session_id: ctx.sessionId,
          tool_name: call.name,
          tool_call_id: call.id,
          tool_args: call.args,
          risk: ctx.risk ?? null,
        }),
      );
      return await decision;
    } catch (error) {
      cancelDecision(error);
      await decision.catch(() => undefined);
      throw error;
    } finally {
      await events.return?.();
    }
  }
}
