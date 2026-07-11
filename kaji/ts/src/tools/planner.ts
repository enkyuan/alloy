/**
 * ToolPlanner: concurrent scatter-gather execution of LLM tool calls.
 * Mirrors `kaji.runtime.agents.planner` from the Python SDK.
 */
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import { defaultUuid } from "@/internal/uuid";
import {
  MissingToolIdentityError,
  assertAbortSignal,
  assertNonEmptyContextId,
  assertValidDeadline,
  normalizePrincipalId,
  snapshotContextMetadata,
  snapshotToolExecutionContext,
  type ToolExecutionContext,
  type TurnContext,
} from "@/runtime/context";
import {
  UnknownToolError,
  assertClassifiedToolSpec,
  snapshotToolSpec,
  type ToolSpec,
} from "@/tools/registry";
import type { ToolPolicy } from "@/tools/policy";
import {
  ToolArgumentValidationError,
  ToolSchemaValidator,
  cloneToolExecutionArguments,
  revokeValidationReceipt,
  validateToolArgumentsForExecution,
  validationFailureFields,
  withValidationReceiptScope,
} from "@/tools/validation";
import type {
  EventBackedApprovalHandler,
  TypedApprovalHandler,
  ToolContext as ApprovalContext,
} from "@/runtime/approval/types";

function isJsonObjectRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
  | {
      id: string;
      name: string;
      error: string;
      error_code?: string;
      error_path?: string;
      retryable?: false;
      outcome?: "not_started" | "failed";
    };

export type ToolExecutor = (
  name: string,
  args: Readonly<Record<string, unknown>>,
  context: ToolExecutionContext,
) => Promise<unknown>;
export type ApprovalHandler = (
  name: string,
  args: Record<string, unknown>,
  risk: string | undefined,
) => Promise<boolean>;
export type EmitFn = (event: KajiEvent) => Promise<void>;

/** Either a legacy function-style handler or the new structured handler. */
export type AnyApprovalHandler =
  | ApprovalHandler
  | TypedApprovalHandler
  | EventBackedApprovalHandler;

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
   *
   * The whole batch is validated before lifecycle events begin.
   */
  async executeScatterGather(
    sessionId: string,
    toolCalls: ToolCallInstruction[],
    emit: EmitFn,
    turnId?: string,
    turnContext?: TurnContext,
    signal: AbortSignal = new AbortController().signal,
  ): Promise<ToolCallResult[]> {
    if (turnContext?.principalId === undefined) throw new MissingToolIdentityError();
    assertNonEmptyContextId(sessionId, "sessionId");
    const resolvedTurnId = turnId ?? this.uuid();
    assertNonEmptyContextId(resolvedTurnId, "turnId");
    const principalId = normalizePrincipalId(turnContext.principalId);
    const requestId = turnContext.requestId ?? this.uuid();
    const traceId = turnContext.traceId ?? this.uuid();
    assertNonEmptyContextId(requestId, "requestId");
    assertNonEmptyContextId(traceId, "traceId");
    assertValidDeadline(turnContext.deadlineMs);
    assertAbortSignal(signal);
    const resolvedTurnContext = Object.freeze({
      principalId,
      requestId,
      traceId,
      ...(turnContext.deadlineMs === undefined ? {} : { deadlineMs: turnContext.deadlineMs }),
      ...(turnContext.db === undefined ? {} : { db: turnContext.db }),
      metadata: snapshotContextMetadata(turnContext.metadata),
    });
    const callIds = new Set<string>();
    const preparedCalls = toolCalls.map((call) => {
      const id = call.id ?? this.uuid();
      assertNonEmptyContextId(id, "toolCallId");
      if (callIds.has(id)) throw new TypeError(`Duplicate toolCallId: ${id}`);
      callIds.add(id);
      return { ...call, id };
    });
    for (const call of preparedCalls) {
      const spec = this.specs.get(call.name);
      if (spec === undefined) throw new UnknownToolError(call.name);
      assertClassifiedToolSpec(spec);
      if (spec.enabled === false) throw new UnknownToolError(call.name);
    }
    return Promise.all(
      preparedCalls.map((call) =>
        this.executeSingle(
          sessionId,
          call,
          emit,
          resolvedTurnId,
          resolvedTurnContext,
          signal,
          turnId !== undefined && turnId.length > 0,
        ),
      ),
    );
  }

  private async executeSingle(
    sessionId: string,
    call: ToolCallInstruction,
    emit: EmitFn,
    turnId: string,
    turnContext: Readonly<{
      principalId: string;
      requestId: string;
      traceId: string;
      deadlineMs?: number;
      db?: unknown;
      metadata: Readonly<Record<string, unknown>>;
    }>,
    signal: AbortSignal,
    turnIdProvided: boolean,
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
    const callId = call.id!;
    const executionContext = snapshotToolExecutionContext({
      principalId: turnContext.principalId,
      sessionId,
      turnId,
      requestId: turnContext.requestId,
      traceId: turnContext.traceId,
      toolCallId: callId,
      idempotencyKey: `${sessionId}:${callId}`,
      signal,
      ...(turnContext.deadlineMs === undefined ? {} : { deadlineMs: turnContext.deadlineMs }),
      ...(turnContext.db === undefined ? {} : { db: turnContext.db }),
      metadata: turnContext.metadata,
    });
    const spec = this.specs.get(toolName)!;
    const risk = spec.risk;
    const catalogName = spec.catalogName;
    const aliases = catalogName ? [catalogName] : [];
    const metadata = catalogName ? { catalog_name: catalogName } : {};
    const eventTurnContext = { turn_id: turnId };

    // 1. Announce intent
    await emit(
      KajiEvent.parse({
        type: EventType.TOOL_CALL_REQUESTED,
        session_id: sessionId,
        ...eventTurnContext,
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
          ...eventTurnContext,
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
            ...eventTurnContext,
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
              ...eventTurnContext,
              tool_name: toolName,
              tool_call_id: callId,
              tool_args: cloneToolExecutionArguments(toolName, toolArgs),
              risk,
              metadata,
            }),
          );
        }

        let approved = false;
        let rejectedReason = "Rejected by approval handler";
        if (this.approvalHandler !== undefined) {
          try {
            if (typeof this.approvalHandler === "function") {
              approved = await this.approvalHandler(
                toolName,
                cloneToolExecutionArguments(toolName, toolArgs),
                risk,
              );
            } else if (this.approvalHandler.emitsApprovalRequest === true) {
              if (!turnIdProvided) {
                rejectedReason = "Event approval requires a non-empty turn identity";
              } else {
                const decision = await this.approvalHandler.request(
                  {
                    id: callId,
                    name: toolName,
                    args: cloneToolExecutionArguments(toolName, toolArgs),
                  },
                  { sessionId, risk, turnId },
                );
                approved = decision.granted;
                if (!approved && decision.reason) {
                  rejectedReason = decision.reason;
                }
              }
            } else {
              const approvalCtx: ApprovalContext = {
                sessionId,
                risk,
                turnId,
              };
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
          } catch (error) {
            console.error(error);
            const reason = "Approval handler unavailable";
            const errorMsg = "Tool approval unavailable";
            const failure = {
              error_code: "APPROVAL_UNAVAILABLE" as const,
              retryable: false as const,
              outcome: "not_started" as const,
            };
            await emit(
              KajiEvent.parse({
                type: EventType.TOOL_APPROVAL_REJECTED,
                session_id: sessionId,
                ...eventTurnContext,
                tool_name: toolName,
                tool_call_id: callId,
                reason,
                metadata,
              }),
            );
            await emit(
              KajiEvent.parse({
                type: EventType.TOOL_CALL_FAILED,
                session_id: sessionId,
                ...eventTurnContext,
                tool_name: toolName,
                tool_call_id: callId,
                error: errorMsg,
                metadata,
                ...failure,
              }),
            );
            return { id: callId, name: toolName, error: errorMsg, ...failure };
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
              ...eventTurnContext,
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
              ...eventTurnContext,
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
            ...eventTurnContext,
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
          ...eventTurnContext,
          tool_name: toolName,
          tool_call_id: callId,
          metadata,
        }),
      );

      // 5. Execute
      try {
        const execute = () => this.executor(toolName, toolArgs, executionContext);
        const result = await withValidationReceiptScope(validationReceipt, execute);
        await emit(
          KajiEvent.parse({
            type: EventType.TOOL_CALL_COMPLETED,
            session_id: sessionId,
            ...eventTurnContext,
            tool_name: toolName,
            tool_call_id: callId,
            result,
            metadata,
          }),
        );
        return { id: callId, name: toolName, result };
      } catch (err) {
        console.error(err);
        const errorMsg = "Tool execution failed";
        const failure = {
          error_code: "TOOL_EXECUTION_FAILED" as const,
          retryable: false as const,
          outcome: "failed" as const,
        };
        await emit(
          KajiEvent.parse({
            type: EventType.TOOL_CALL_FAILED,
            session_id: sessionId,
            ...eventTurnContext,
            tool_name: toolName,
            tool_call_id: callId,
            error: errorMsg,
            metadata,
            ...failure,
          }),
        );
        return { id: callId, name: toolName, error: errorMsg, ...failure };
      }
    } finally {
      revokeValidationReceipt(validationReceipt);
    }
  }
}
