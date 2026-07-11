/** Bounded, ordered planning and execution of provider tool calls. */
import { KajiEvent } from "@/events/schemas";
import { EventType } from "@/events/types";
import { defaultUuid } from "@/internal/uuid";
import type {
  EventBackedApprovalHandler,
  ToolContext as ApprovalContext,
  TypedApprovalHandler,
} from "@/runtime/approval/types";
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
  ToolExecutionController,
  type ToolExecutionControllerOutcome,
  type ToolExecutionLimits,
} from "@/tools/execution";
import type { ToolExecutionError } from "@/tools/execution-errors";
import type { ToolIdempotencyLedger } from "@/tools/idempotency";
import type { ToolPolicy } from "@/tools/policy";
import {
  UnknownToolError,
  assertClassifiedToolSpec,
  snapshotToolSpec,
  type ToolSpec,
} from "@/tools/registry";
import {
  ToolArgumentValidationError,
  ToolSchemaValidator,
  cloneToolExecutionArguments,
  revokeValidationReceipt,
  validateToolArgumentsForExecution,
  validationFailureFields,
  withValidationReceiptScope,
} from "@/tools/validation";

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
      retryable?: boolean;
      outcome?: "not_started" | "failed" | "unknown";
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

export type AnyApprovalHandler =
  | ApprovalHandler
  | TypedApprovalHandler
  | EventBackedApprovalHandler;

export interface ToolPlannerOptions {
  executor: ToolExecutor;
  policy?: ToolPolicy;
  approvalHandler?: AnyApprovalHandler;
  specs?: ReadonlyMap<string, ToolSpec>;
  uuid?: () => string;
  executionController?: ToolExecutionController;
  executionLimits?: Partial<ToolExecutionLimits>;
  idempotencyLedger?: ToolIdempotencyLedger;
}

interface ResolvedTurnContext {
  readonly principalId: string;
  readonly requestId: string;
  readonly traceId: string;
  readonly deadlineMs?: number;
  readonly db?: unknown;
  readonly metadata: Readonly<Record<string, unknown>>;
}

type ValidationReceipt = Awaited<ReturnType<typeof validateToolArgumentsForExecution>>;

interface NormalizedCall {
  readonly id: string;
  readonly name: string;
  readonly args: Record<string, unknown>;
  readonly spec: ToolSpec;
  readonly context: ToolExecutionContext;
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly validationError?: ToolArgumentValidationError;
}

interface PreparedCall extends NormalizedCall {
  readonly receipt: ValidationReceipt;
}

interface FailureDraft {
  readonly status: "failed";
  readonly error: string;
  readonly error_code?: string;
  readonly error_path?: string;
  readonly retryable?: boolean;
  readonly outcome?: "not_started" | "failed" | "unknown";
}

interface SuccessDraft {
  readonly status: "completed";
  readonly result: unknown;
}

type TerminalDraft = FailureDraft | SuccessDraft;
type PlannedCall =
  | { readonly status: "prepared"; readonly call: PreparedCall }
  | { readonly status: "terminal"; readonly call: NormalizedCall; readonly draft: FailureDraft }
  | { readonly status: "recording_failed"; readonly call: NormalizedCall; readonly error: unknown };

function failureFromExecution(error: ToolExecutionError): FailureDraft {
  return {
    status: "failed",
    error: error.message,
    error_code: error.error_code,
    retryable: error.retryable,
    outcome: error.outcome,
  };
}

function normalizeArguments(
  toolName: string,
  raw: unknown,
): { args: Record<string, unknown>; validationError?: ToolArgumentValidationError } {
  if (!isJsonObjectRecord(raw)) {
    return {
      args: { __parse_error: "invalid arguments" },
      validationError: ToolArgumentValidationError.nonObject(toolName),
    };
  }
  try {
    const parseError = Object.getOwnPropertyDescriptor(raw, "__parse_error");
    if (
      parseError !== undefined &&
      parseError.enumerable &&
      "value" in parseError &&
      typeof parseError.value === "string"
    ) {
      return {
        args: { __parse_error: "invalid JSON" },
        validationError: ToolArgumentValidationError.parseError(toolName),
      };
    }
    return { args: cloneToolExecutionArguments(toolName, raw) };
  } catch (error) {
    return {
      args: { __parse_error: "invalid arguments" },
      validationError:
        error instanceof ToolArgumentValidationError
          ? error
          : ToolArgumentValidationError.jsonUnsafe(toolName, "/"),
    };
  }
}

export class ToolPlanner {
  private readonly executor: ToolExecutor;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: AnyApprovalHandler | undefined;
  private readonly specs: Map<string, ToolSpec>;
  private readonly schemaValidator: ToolSchemaValidator;
  private readonly uuid: () => string;
  readonly executionController: ToolExecutionController;

  constructor(opts: ToolPlannerOptions) {
    if (
      opts.executionController !== undefined &&
      (opts.executionLimits !== undefined || opts.idempotencyLedger !== undefined)
    ) {
      throw new TypeError(
        "executionController cannot be combined with executionLimits or idempotencyLedger",
      );
    }
    this.executor = opts.executor;
    this.policy = opts.policy;
    this.approvalHandler = opts.approvalHandler;
    this.specs = new Map(
      [...(opts.specs ?? new Map())].map(([name, spec]) => [name, snapshotToolSpec(spec)]),
    );
    this.schemaValidator = new ToolSchemaValidator(this.specs);
    this.uuid = opts.uuid ?? defaultUuid;
    this.executionController =
      opts.executionController ??
      new ToolExecutionController({ limits: opts.executionLimits, ledger: opts.idempotencyLedger });
  }

  /**
   * Execute one provider batch with bounded parallelism and provider-order
   * request/result/terminal semantics. Explicitly parallel-safe runs overlap;
   * every unmarked tool is an exclusive barrier.
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
    const resolvedTurnContext: ResolvedTurnContext = Object.freeze({
      principalId,
      requestId,
      traceId,
      ...(turnContext.deadlineMs === undefined ? {} : { deadlineMs: turnContext.deadlineMs }),
      ...(turnContext.db === undefined ? {} : { db: turnContext.db }),
      metadata: snapshotContextMetadata(turnContext.metadata),
    });

    const calls = this.normalizeCalls(
      sessionId,
      resolvedTurnId,
      resolvedTurnContext,
      signal,
      toolCalls,
    );
    const requestedErrors = new Map<number, unknown>();
    for (const [index, call] of calls.entries()) {
      try {
        await emit(this.requestedEvent(sessionId, resolvedTurnId, call));
      } catch (error) {
        requestedErrors.set(index, error);
      }
    }

    const planned: PlannedCall[] = [];
    for (const [index, call] of calls.entries()) {
      const recordingError = requestedErrors.get(index);
      if (recordingError !== undefined) {
        planned.push({ status: "recording_failed", call, error: recordingError });
        continue;
      }
      try {
        planned.push(
          await this.preflight(sessionId, resolvedTurnId, call, emit, turnId !== undefined),
        );
      } catch (error) {
        planned.push({ status: "recording_failed", call, error });
      }
    }

    const slots: Array<TerminalDraft | { readonly recordingError: unknown }> = new Array(
      calls.length,
    );
    let index = 0;
    while (index < planned.length) {
      const item = planned[index]!;
      if (item.status === "recording_failed") {
        slots[index] = { recordingError: item.error };
        index++;
        continue;
      }
      if (item.status === "terminal") {
        slots[index] = item.draft;
        index++;
        continue;
      }
      if (item.call.spec.parallel_safe === true) {
        const group: Array<{ index: number; call: PreparedCall }> = [];
        while (index < planned.length) {
          const candidate = planned[index]!;
          if (candidate.status !== "prepared" || candidate.call.spec.parallel_safe !== true) break;
          group.push({ index, call: candidate.call });
          index++;
        }
        // Preserve the existing plumbing-failure contract: every sibling is
        // allowed to settle before recording errors are aggregated.
        await this.executeParallelGroup(group, slots, sessionId, resolvedTurnId, emit);
        continue;
      }
      try {
        slots[index] = await this.executePrepared(sessionId, resolvedTurnId, item.call, emit);
      } catch (error) {
        slots[index] = { recordingError: error };
      }
      index++;
    }

    const results: ToolCallResult[] = [];
    const recordingErrors: unknown[] = [];
    for (const [slotIndex, call] of calls.entries()) {
      const slot = slots[slotIndex]!;
      if ("recordingError" in slot) {
        recordingErrors.push(slot.recordingError);
        continue;
      }
      const result: ToolCallResult =
        slot.status === "completed"
          ? { id: call.id, name: call.name, result: slot.result }
          : {
              id: call.id,
              name: call.name,
              error: slot.error,
              ...(slot.error_code === undefined ? {} : { error_code: slot.error_code }),
              ...(slot.error_path === undefined ? {} : { error_path: slot.error_path }),
              ...(slot.retryable === undefined ? {} : { retryable: slot.retryable }),
              ...(slot.outcome === undefined ? {} : { outcome: slot.outcome }),
            };
      results.push(result);
      try {
        await emit(this.terminalEvent(sessionId, resolvedTurnId, call, slot));
      } catch (error) {
        // Never emit a fallback failed event after an ambiguous completed append.
        recordingErrors.push(error);
      }
    }
    if (recordingErrors.length > 0) {
      throw new AggregateError(
        recordingErrors,
        `${recordingErrors.length} of ${toolCalls.length} tool call(s) failed to record their events`,
      );
    }
    return results;
  }

  private async executeParallelGroup(
    group: ReadonlyArray<{ index: number; call: PreparedCall }>,
    slots: Array<TerminalDraft | { readonly recordingError: unknown }>,
    sessionId: string,
    turnId: string,
    emit: EmitFn,
  ): Promise<void> {
    let next = 0;
    const worker = async () => {
      while (next < group.length) {
        const item = group[next++]!;
        try {
          slots[item.index] = await this.executePrepared(sessionId, turnId, item.call, emit);
        } catch (error) {
          slots[item.index] = { recordingError: error };
        }
      }
    };
    const workers: Promise<void>[] = [];
    const count = Math.min(group.length, this.executionController.limits.maxParallel);
    for (let workerIndex = 0; workerIndex < count; workerIndex++) workers.push(worker());
    await Promise.all(workers);
  }

  private normalizeCalls(
    sessionId: string,
    turnId: string,
    turnContext: ResolvedTurnContext,
    signal: AbortSignal,
    toolCalls: ToolCallInstruction[],
  ): NormalizedCall[] {
    const ids = new Set<string>();
    return toolCalls.map((instruction) => {
      const id = instruction.id ?? this.uuid();
      assertNonEmptyContextId(id, "toolCallId");
      if (ids.has(id)) throw new TypeError(`Duplicate toolCallId: ${id}`);
      ids.add(id);
      const spec = this.specs.get(instruction.name);
      if (spec === undefined) throw new UnknownToolError(instruction.name);
      assertClassifiedToolSpec(spec);
      if (spec.enabled === false) throw new UnknownToolError(instruction.name);
      const normalized = normalizeArguments(instruction.name, instruction.arguments);
      const context = snapshotToolExecutionContext({
        principalId: turnContext.principalId,
        sessionId,
        turnId,
        requestId: turnContext.requestId,
        traceId: turnContext.traceId,
        toolCallId: id,
        idempotencyKey: `${sessionId}:${id}`,
        signal,
        ...(turnContext.deadlineMs === undefined ? {} : { deadlineMs: turnContext.deadlineMs }),
        ...(turnContext.db === undefined ? {} : { db: turnContext.db }),
        metadata: turnContext.metadata,
      });
      const catalogName = spec.catalogName;
      return {
        id,
        name: instruction.name,
        args: normalized.args,
        spec,
        context,
        metadata: catalogName ? Object.freeze({ catalog_name: catalogName }) : Object.freeze({}),
        ...(normalized.validationError === undefined
          ? {}
          : { validationError: normalized.validationError }),
      };
    });
  }

  private requestedEvent(sessionId: string, turnId: string, call: NormalizedCall): KajiEvent {
    return KajiEvent.parse({
      type: EventType.TOOL_CALL_REQUESTED,
      session_id: sessionId,
      turn_id: turnId,
      tool_name: call.name,
      tool_args: cloneToolExecutionArguments(call.name, call.args),
      tool_call_id: call.id,
      metadata: call.metadata,
    });
  }

  private async preflight(
    sessionId: string,
    turnId: string,
    call: NormalizedCall,
    emit: EmitFn,
    turnIdProvided: boolean,
  ): Promise<PlannedCall> {
    let validationError = call.validationError;
    let receipt: ValidationReceipt = undefined;
    if (validationError === undefined) {
      try {
        receipt = await validateToolArgumentsForExecution(
          this.schemaValidator,
          call.name,
          call.args,
        );
      } catch (error) {
        if (!(error instanceof ToolArgumentValidationError)) throw error;
        validationError = error;
      }
    }
    if (validationError !== undefined) {
      const fields = validationFailureFields(validationError);
      return {
        status: "terminal",
        call,
        draft: { status: "failed", error: validationError.message, ...fields },
      };
    }

    const aliases = call.spec.catalogName ? [call.spec.catalogName] : [];
    if (this.policy !== undefined && !this.policy.isAllowedAny([call.name, ...aliases])) {
      revokeValidationReceipt(receipt);
      return {
        status: "terminal",
        call,
        draft: { status: "failed", error: `Tool not permitted: ${call.name}` },
      };
    }

    if (this.policy?.requiresApproval(call.name, call.spec.risk)) {
      const handlerPublishesRequest =
        this.approvalHandler !== undefined &&
        typeof this.approvalHandler !== "function" &&
        this.approvalHandler.emitsApprovalRequest === true;
      if (!handlerPublishesRequest) {
        await emit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REQUESTED,
            session_id: sessionId,
            turn_id: turnId,
            tool_name: call.name,
            tool_call_id: call.id,
            tool_args: cloneToolExecutionArguments(call.name, call.args),
            risk: call.spec.risk,
            metadata: call.metadata,
          }),
        );
      }

      let approved = false;
      let rejectedReason = "Rejected by approval handler";
      try {
        if (typeof this.approvalHandler === "function") {
          approved = await this.approvalHandler(
            call.name,
            cloneToolExecutionArguments(call.name, call.args),
            call.spec.risk,
          );
        } else if (this.approvalHandler?.emitsApprovalRequest === true) {
          if (!turnIdProvided) {
            rejectedReason = "Event approval requires a non-empty turn identity";
          } else {
            const decision = await this.approvalHandler.request(
              {
                id: call.id,
                name: call.name,
                args: cloneToolExecutionArguments(call.name, call.args),
              },
              { sessionId, risk: call.spec.risk, turnId },
            );
            approved = decision.granted;
            if (!approved && decision.reason) rejectedReason = decision.reason;
          }
        } else if (this.approvalHandler !== undefined) {
          const context: ApprovalContext = { sessionId, risk: call.spec.risk, turnId };
          const decision = await this.approvalHandler.request(
            {
              id: call.id,
              name: call.name,
              args: cloneToolExecutionArguments(call.name, call.args),
            },
            context,
          );
          approved = decision.granted;
          if (!approved && decision.reason) rejectedReason = decision.reason;
        }
      } catch (error) {
        console.error(error);
        revokeValidationReceipt(receipt);
        await emit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REJECTED,
            session_id: sessionId,
            turn_id: turnId,
            tool_name: call.name,
            tool_call_id: call.id,
            reason: "Approval handler unavailable",
            metadata: call.metadata,
          }),
        );
        return {
          status: "terminal",
          call,
          draft: {
            status: "failed",
            error: "Tool approval unavailable",
            error_code: "APPROVAL_UNAVAILABLE",
            retryable: false,
            outcome: "not_started",
          },
        };
      }

      if (!approved) {
        revokeValidationReceipt(receipt);
        const reason =
          this.approvalHandler === undefined ? "No approval handler registered" : rejectedReason;
        await emit(
          KajiEvent.parse({
            type: EventType.TOOL_APPROVAL_REJECTED,
            session_id: sessionId,
            turn_id: turnId,
            tool_name: call.name,
            tool_call_id: call.id,
            reason,
            metadata: call.metadata,
          }),
        );
        return {
          status: "terminal",
          call,
          draft: { status: "failed", error: `Tool approval rejected: ${reason}` },
        };
      }

      await emit(
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_APPROVED,
          session_id: sessionId,
          turn_id: turnId,
          tool_name: call.name,
          tool_call_id: call.id,
          metadata: call.metadata,
        }),
      );
    }
    return { status: "prepared", call: { ...call, receipt } };
  }

  private async executePrepared(
    sessionId: string,
    turnId: string,
    call: PreparedCall,
    emit: EmitFn,
  ): Promise<TerminalDraft> {
    let started = false;
    let outcome: ToolExecutionControllerOutcome;
    try {
      outcome = await this.executionController.execute({
        name: call.name,
        args: call.args,
        context: call.context,
        timeoutMs: call.spec.timeout_ms,
        exclusive: call.spec.parallel_safe !== true,
        onStarted: async () => {
          await emit(
            KajiEvent.parse({
              type: EventType.TOOL_CALL_STARTED,
              session_id: sessionId,
              turn_id: turnId,
              tool_name: call.name,
              tool_call_id: call.id,
              metadata: call.metadata,
            }),
          );
          started = true;
        },
        execute: (context) =>
          withValidationReceiptScope(call.receipt, () =>
            this.executor(call.name, call.args, context),
          ),
      });
    } catch (error) {
      if (!started) revokeValidationReceipt(call.receipt);
      throw error;
    }
    if (!started) revokeValidationReceipt(call.receipt);
    if (outcome.status === "completed") return outcome;
    if (outcome.error.cause !== undefined) console.error(outcome.error.cause);
    return failureFromExecution(outcome.error);
  }

  private terminalEvent(
    sessionId: string,
    turnId: string,
    call: NormalizedCall,
    draft: TerminalDraft,
  ): KajiEvent {
    if (draft.status === "completed") {
      return KajiEvent.parse({
        type: EventType.TOOL_CALL_COMPLETED,
        session_id: sessionId,
        turn_id: turnId,
        tool_name: call.name,
        tool_call_id: call.id,
        result: draft.result,
        metadata: call.metadata,
      });
    }
    return KajiEvent.parse({
      type: EventType.TOOL_CALL_FAILED,
      session_id: sessionId,
      turn_id: turnId,
      tool_name: call.name,
      tool_call_id: call.id,
      error: draft.error,
      metadata: call.metadata,
      ...(draft.error_code === undefined ? {} : { error_code: draft.error_code }),
      ...(draft.error_path === undefined ? {} : { error_path: draft.error_path }),
      ...(draft.retryable === undefined ? {} : { retryable: draft.retryable }),
      ...(draft.outcome === undefined ? {} : { outcome: draft.outcome }),
    });
  }
}
