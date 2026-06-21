/**
 * ToolPlanner: concurrent scatter-gather execution of LLM tool calls.
 * Mirrors `agentkit.runtime.agents.planner` from the Python SDK.
 */
import { AgentKitEvent } from "../events/schemas";
import { EventType } from "../events/types";
import type { ToolSpec } from "./registry";
import type { ToolPolicy } from "./policy";

const JSON_TYPE_CHECK: Record<string, (v: unknown) => boolean> = {
  object: (v) => typeof v === "object" && v !== null && !Array.isArray(v),
  array: Array.isArray,
  string: (v) => typeof v === "string",
  integer: (v) => typeof v === "number" && Number.isInteger(v),
  number: (v) => typeof v === "number",
  boolean: (v) => typeof v === "boolean",
  null: (v) => v === null,
};

/** Shallow JSON Schema check against ToolSpec.parameters. Returns null on success. */
function validateArgs(spec: ToolSpec, args: Record<string, unknown>): string | null {
  const schema = (spec.parameters ?? {}) as Record<string, unknown>;
  if (
    schema.type === "object" &&
    (typeof args !== "object" || args === null || Array.isArray(args))
  ) {
    return `arguments must be an object, got ${Array.isArray(args) ? "array" : typeof args}`;
  }
  const required = (schema.required as string[] | undefined) ?? [];
  for (const key of required) {
    if (!(key in args)) return `missing required argument: '${key}'`;
  }
  const properties = (schema.properties as Record<string, { type?: string }> | undefined) ?? {};
  for (const [key, propSchema] of Object.entries(properties)) {
    if (!(key in args)) continue;
    const expected = propSchema?.type;
    if (!expected) continue;
    const check = JSON_TYPE_CHECK[expected];
    if (check && !check(args[key])) {
      return `argument '${key}': expected ${expected}, got ${typeof args[key]}`;
    }
  }
  return null;
}

const ERROR_MSG_MAX = 200;

/** Return a log-safe error string. Includes class name and a length-capped message. */
function sanitizeError(err: unknown): string {
  if (err instanceof Error) {
    const msg =
      err.message.length > ERROR_MSG_MAX ? err.message.slice(0, ERROR_MSG_MAX) + "…" : err.message;
    return msg ? `${err.name}: ${msg}` : err.name;
  }
  const s = String(err);
  return s.length > ERROR_MSG_MAX ? s.slice(0, ERROR_MSG_MAX) + "…" : s;
}

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
    const catalogName = spec?.catalogName;
    const aliases = catalogName ? [catalogName] : [];
    const metadata = catalogName ? { catalog_name: catalogName } : {};

    // 1. Announce intent
    await emit(
      AgentKitEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: sessionId,
        tool_name: toolName,
        tool_args: toolArgs,
        tool_call_id: callId,
        metadata,
      }),
    );

    // 2a. Provider parse-error sentinel: model produced unparseable tool JSON.
    if (typeof toolArgs.__parse_error === "string") {
      const errorMsg = `Invalid tool arguments: ${toolArgs.__parse_error}`;
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: errorMsg,
          metadata,
        }),
      );
      return { id: callId, name: toolName, error: errorMsg };
    }

    // 2b. Schema validation: fail closed on malformed args from the model.
    if (spec !== undefined) {
      const schemaError = validateArgs(spec, toolArgs);
      if (schemaError !== null) {
        const errorMsg = `Invalid tool arguments: ${schemaError}`;
        await emit(
          AgentKitEvent.parse({
            type: EventType.TOOL_CALL_FAILED,
            session_id: sessionId,
            tool_name: toolName,
            tool_call_id: callId,
            error: errorMsg,
            metadata,
          }),
        );
        return { id: callId, name: toolName, error: errorMsg };
      }
    }

    // 3. Allow/deny gate: policy violations fail before approval/execution.
    if (this.policy !== undefined && !this.policy.isAllowedAny([toolName, ...aliases])) {
      const errorMsg = `Tool not permitted: ${toolName}`;
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: errorMsg,
          metadata,
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
          metadata,
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
            metadata,
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
            metadata,
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
          metadata,
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
        metadata,
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
          metadata,
        }),
      );
      return { id: callId, name: toolName, result };
    } catch (err) {
      const errorMsg = sanitizeError(err);
      await emit(
        AgentKitEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: errorMsg,
          metadata,
        }),
      );
      return { id: callId, name: toolName, error: errorMsg };
    }
  }
}
