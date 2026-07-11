/**
 * ToolPlanner: concurrent scatter-gather execution of LLM tool calls.
 * Mirrors `kaji.runtime.agents.planner` from the Python SDK.
 */
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import { defaultUuid } from "@/internal/uuid";
import { snapshotToolSpec, type ToolSpec } from "@/tools/registry";
import type { ToolPolicy } from "@/tools/policy";
import {
  ToolArgumentValidationError,
  ToolSchemaValidator,
  cloneToolExecutionArguments,
  revokeValidationReceipt,
  validateToolArgumentsForExecution,
  validationFailureFields,
  withValidationReceiptScope,
  type ValidationFailureFields,
} from "@/tools/validation";
import type {
  TypedApprovalHandler,
  ToolContext as ApprovalContext,
} from "@/runtime/approval/types";

function isJsonObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  | ({ id: string; name: string; error: string } & Partial<ValidationFailureFields>);

export type ToolExecutor = (name: string, args: Record<string, unknown>) => Promise<unknown>;
export type ApprovalHandler = (
  name: string,
  args: Record<string, unknown>,
  risk: string | undefined,
) => Promise<boolean>;
export type EmitFn = (event: KajiEvent) => Promise<void>;

/** Either a legacy function-style handler or the new structured handler. */
export type AnyApprovalHandler = ApprovalHandler | TypedApprovalHandler;

export interface ToolPlannerOptions {
  executor: ToolExecutor;
  policy?: ToolPolicy;
  /**
   * Approval gate invoked when policy requires approval. Accepts either the
   * legacy `(name, args, risk) => Promise<boolean>` function form or the new
   * `TypedApprovalHandler` object form (duck-typed: has a `.request` method).
   */
  approvalHandler?: AnyApprovalHandler;
  specs?: ReadonlyMap<string, ToolSpec>;
  /**
   * Override the call-id generator. Defaults to `globalThis.crypto.randomUUID`
   * with a `Math.random` fallback for runtimes without Web Crypto.
   */
  uuid?: () => string;
}

export class ToolPlanner {
  private readonly executor: ToolExecutor;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: AnyApprovalHandler | undefined;
  private readonly specs: Map<string, ToolSpec>;
  private readonly schemaValidator: ToolSchemaValidator;
  private readonly uuid: () => string;

  constructor(opts: ToolPlannerOptions) {
    this.executor = opts.executor;
    this.policy = opts.policy;
    this.approvalHandler = opts.approvalHandler;
    this.specs = new Map(
      [...(opts.specs ?? new Map())].map(([name, spec]) => [name, snapshotToolSpec(spec)]),
    );
    this.schemaValidator = new ToolSchemaValidator(this.specs);
    this.uuid = opts.uuid ?? defaultUuid;
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
    const rawToolArgs: unknown = call.arguments;
    let validationError: ToolArgumentValidationError | undefined;
    let toolArgs: Record<string, unknown>;
    if (!isJsonObjectRecord(rawToolArgs)) {
      toolArgs = { __parse_error: "invalid arguments" };
      validationError = ToolArgumentValidationError.nonObject(toolName);
    } else {
      try {
        const parseError = Object.getOwnPropertyDescriptor(rawToolArgs, "__parse_error");
        if (
          parseError !== undefined &&
          parseError.enumerable &&
          "value" in parseError &&
          typeof parseError.value === "string"
        ) {
          toolArgs = { __parse_error: "invalid JSON" };
          validationError = ToolArgumentValidationError.parseError(toolName);
        } else {
          toolArgs = cloneToolExecutionArguments(toolName, rawToolArgs);
        }
      } catch (error) {
        validationError =
          error instanceof ToolArgumentValidationError
            ? error
            : ToolArgumentValidationError.jsonUnsafe(toolName, "/");
        toolArgs = { __parse_error: "invalid arguments" };
      }
    }
    const callId = call.id ?? this.uuid();
    const spec = this.specs.get(toolName);
    const risk = spec?.risk;
    const catalogName = spec?.catalogName;
    const aliases = catalogName ? [catalogName] : [];
    const metadata = catalogName ? { catalog_name: catalogName } : {};

    // 1. Announce intent
    await emit(
      KajiEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: sessionId,
        tool_name: toolName,
        tool_args: cloneToolExecutionArguments(toolName, toolArgs),
        tool_call_id: callId,
        metadata,
      }),
    );

    // 2. Fail closed on provider parse errors and complete schema violations.
    let validationReceipt: Awaited<ReturnType<typeof validateToolArgumentsForExecution>> =
      undefined;
    if (validationError === undefined) {
      try {
        validationReceipt = await validateToolArgumentsForExecution(
          this.schemaValidator,
          toolName,
          toolArgs,
        );
      } catch (error) {
        if (!(error instanceof ToolArgumentValidationError)) throw error;
        validationError = error;
      }
    }
    if (validationError !== undefined) {
      const failureFields = validationFailureFields(validationError);
      await emit(
        KajiEvent.parse({
          type: EventType.TOOL_CALL_FAILED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          error: validationError.message,
          metadata,
          ...failureFields,
        }),
      );
      return {
        id: callId,
        name: toolName,
        error: validationError.message,
        ...failureFields,
      };
    }

    try {
      // 3. Allow/deny gate: policy violations fail before approval/execution.
      if (this.policy !== undefined && !this.policy.isAllowedAny([toolName, ...aliases])) {
        const errorMsg = `Tool not permitted: ${toolName}`;
        await emit(
          KajiEvent.parse({
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
        const handlerPublishesApprovalRequest =
          this.approvalHandler !== undefined &&
          typeof this.approvalHandler !== "function" &&
          this.approvalHandler.emitsApprovalRequest === true;

        if (!handlerPublishesApprovalRequest) {
          await emit(
            KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_REQUESTED,
              session_id: sessionId,
              tool_name: toolName,
              tool_call_id: callId,
              tool_args: cloneToolExecutionArguments(toolName, toolArgs),
              risk: risk ?? null,
              metadata,
            }),
          );
        }

        let approved = false;
        let rejectedReason = "Rejected by approval handler";
        if (this.approvalHandler !== undefined) {
          if (typeof this.approvalHandler === "function") {
            approved = await this.approvalHandler(
              toolName,
              cloneToolExecutionArguments(toolName, toolArgs),
              risk,
            );
          } else {
            const approvalCtx: ApprovalContext = { sessionId, risk };
            const decision = await this.approvalHandler.request(
              {
                id: callId,
                name: toolName,
                args: cloneToolExecutionArguments(toolName, toolArgs),
              },
              approvalCtx,
            );
            approved = decision.granted;
            if (!approved && decision.reason) {
              rejectedReason = decision.reason;
            }
          }
        }

        if (!approved) {
          const reason =
            this.approvalHandler === undefined ? "No approval handler registered" : rejectedReason;
          const errorMsg = `Tool approval rejected: ${reason}`;
          await emit(
            KajiEvent.parse({
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
            KajiEvent.parse({
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
          KajiEvent.parse({
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
        KajiEvent.parse({
          type: EventType.TOOL_CALL_STARTED,
          session_id: sessionId,
          tool_name: toolName,
          tool_call_id: callId,
          metadata,
        }),
      );

      // 5. Execute
      try {
        const execute = () => this.executor(toolName, toolArgs);
        const result = await withValidationReceiptScope(validationReceipt, execute);
        await emit(
          KajiEvent.parse({
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
          KajiEvent.parse({
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
    } finally {
      revokeValidationReceipt(validationReceipt);
    }
  }
}
