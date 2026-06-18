/**
 * ToolPlanner: concurrent scatter-gather execution of LLM tool calls.
 * Mirrors `agentkit.runtime.agents.planner` from the Python SDK.
 */
import { AgentKitEvent } from "../events/schemas";
import { EventType } from "../events/types";
import type { ToolSpec } from "./registry";
import type { ToolPolicy } from "./policy";

/** A single tool call instruction from the LLM. */
export interface ToolCallInstruction {
  id?: string;
  name: string;
  arguments: Record<string, unknown>;
}

/** Result of a single tool call execution. */
export type ToolCallResult =
  | { id: string; name: string; result: unknown }
  | { id: string; name: string; error: string };

export type ToolExecutor = (name: string, args: Record<string, unknown>) => Promise<unknown>;
export type ApprovalHandler = (
  name: string,
  args: Record<string, unknown>,
  risk: string | undefined,
) => Promise<boolean>;
export type EmitFn = (event: AgentKitEvent) => Promise<void>;

export interface ToolPlannerOptions {
  executor: ToolExecutor;
  policy?: ToolPolicy;
  approvalHandler?: ApprovalHandler;
  specs?: Map<string, ToolSpec>;
}

export class ToolPlanner {
  private readonly executor: ToolExecutor;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: ApprovalHandler | undefined;
  private readonly specs: Map<string, ToolSpec>;

  constructor(opts: ToolPlannerOptions) {
    this.executor = opts.executor;
    this.policy = opts.policy;
    this.approvalHandler = opts.approvalHandler;
    this.specs = opts.specs ?? new Map();
  }

  /**
   * Execute all tool calls concurrently (scatter-gather) and collect results.
   *
   * Each call emits `TOOL_CALL_REQUESTED` as its first step before entering
   * the approval/execution phase. For multiple simultaneous calls, lifecycle
   * events from different calls will interleave — e.g. call A's
   * `TOOL_CALL_STARTED` may appear between call B's `TOOL_CALL_REQUESTED` and
   * `TOOL_CALL_STARTED`. Consumers that require strict per-call ordering
   * should correlate events by `tool_call_id`.
   *
   * Approval rejection emits both `TOOL_APPROVAL_REJECTED` and
   * `TOOL_CALL_FAILED` so `replaySession` projects the outcome into
   * model-visible history, preventing the agent from re-requesting the same
   * tool indefinitely.
   */
  async executeScatterGather(
    sessionId: string,
    toolCalls: ToolCallInstruction[],
    emit: EmitFn,
  ): Promise<ToolCallResult[]> {
    return Promise.all(toolCalls.map((call) => this.executeSingle(sessionId, call, emit)));
  }

  private async executeSingle(
    sessionId: string,
    call: ToolCallInstruction,
    emit: EmitFn,
  ): Promise<ToolCallResult> {
    const toolName = call.name;
    const toolArgs = call.arguments;
    const callId = call.id ?? crypto.randomUUID();
    const spec = this.specs.get(toolName);
    const risk = spec?.risk;

    // 1. Announce intent
    await emit(
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: sessionId,
        tool_name: toolName,
        tool_args: toolArgs,
        tool_call_id: callId,
      }),
    );

    // 2. Allow/deny gate: policy violations fail before approval/execution.
    if (this.policy !== undefined && !this.policy.isAllowed(toolName)) {
      const errorMsg = `Tool not permitted: ${toolName}`;
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: errorMsg,
        }),
      );
      return { id: callId, name: toolName, error: errorMsg };
    }

    // 3. Approval gate
    if (this.policy?.requiresApproval(toolName, risk)) {
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_APPROVAL_REQUESTED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          tool_args: toolArgs,
          risk: risk ?? null,
        }),
      );

      let approved = false;
      if (this.approvalHandler !== undefined) {
        approved = await this.approvalHandler(toolName, toolArgs, risk);
      }

      if (!approved) {
        const reason =
          this.approvalHandler === undefined
            ? "No approval handler registered"
            : "Rejected by approval handler";
        const errorMsg = `Tool approval rejected: ${reason}`;
        await emit(
          AgentKitEvent.parse({
            type: EventType.TOOL_APPROVAL_REJECTED,
            session_id: sessionId,
            tool_name: toolName,
            tool_call_id: callId,
            reason,
          }),
        );
        // Also emit TOOL_CALL_FAILED so replaySession projects this into
        // model-visible history. Without it, the next iteration sees no tool
        // result and re-requests the same tool until maxToolIterations.
        await emit(
          AgentKitEvent.parse({
            type: EventType.TOOL_CALL_FAILED,
            session_id: sessionId,
            tool_name: toolName,
            tool_call_id: callId,
            error: errorMsg,
          }),
        );
        return { id: callId, name: toolName, error: errorMsg };
      }

      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_APPROVAL_APPROVED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
        }),
      );
    }

    // 4. Mark execution started
    await emit(
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_STARTED,
        session_id: sessionId,
        tool_name: toolName,
        tool_call_id: callId,
      }),
    );

    // 5. Execute
    try {
      const result = await this.executor(toolName, toolArgs);
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_COMPLETED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          result,
        }),
      );
      return { id: callId, name: toolName, result };
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: errorMsg,
        }),
      );
      return { id: callId, name: toolName, error: errorMsg };
    }
  }
}
