/** Bounded, ordered planning and execution of provider tool calls. */
import { KajiEvent, StoredKajiEvent } from "@/events/schemas";
import { structurallyEqualJson } from "@/events/json";
import { EventType } from "@/events/types";
import type { EventCommitter } from "@/events/protocols";
import { defaultUuid } from "@/internal/uuid";
import type {
  ApprovalDecision,
  ApprovalRejectionCode,
  ApprovalRequestContext,
  EventBackedApprovalHandler,
  LegacyApprovalHandler,
  TypedApprovalHandler,
} from "@/runtime/approval/types";
import { requestLegacyApproval } from "@/runtime/approval/types";
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
import type { MetricsSink, TraceSink } from "@/observability";
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

function reportError(error: unknown): void {
  try {
    console.error(error);
  } catch {
    // Diagnostics are observational and must not alter lifecycle closure.
  }
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
/** @deprecated Return ApprovalDecision from a TypedApprovalHandler instead. */
export type ApprovalHandler = LegacyApprovalHandler;
export type EmitFn = (event: KajiEvent) => Promise<StoredKajiEvent | void>;

const EMITTER_COMMITTER = Symbol("kaji.tool-planner.emitter-committer");
type CommitterBoundEmitFn = EmitFn & {
  readonly [EMITTER_COMMITTER]: EventCommitter;
};

/** Bind a runtime-owned write path to the committer whose journal it updates. */
export function bindEmitterToCommitter(emit: EmitFn, committer: EventCommitter): EmitFn {
  const bound: EmitFn = (event) => emit(event);
  Object.defineProperty(bound, EMITTER_COMMITTER, { value: committer });
  return bound;
}

function emitterCommitter(emit: EmitFn): EventCommitter | undefined {
  return (emit as Partial<CommitterBoundEmitFn>)[EMITTER_COMMITTER];
}

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
  /** Canonical runtime committer used by event-backed approval waiters. */
  approvalCommitter?: EventCommitter;
  /** Wall-clock source used to derive the absolute approval deadline. */
  now?: () => number;
  monotonicNow?: () => number;
  metricsSink?: MetricsSink;
  traceSink?: TraceSink;
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

class ApprovalEventRecordingError extends Error {
  constructor(options: ErrorOptions) {
    super("Approval event recording failed", options);
    this.name = "ApprovalEventRecordingError";
  }
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

function normalizeApprovalDecision(value: unknown): ApprovalDecision {
  if (typeof value !== "object" || value === null || !("granted" in value)) {
    throw new TypeError("Approval handler returned an invalid decision");
  }
  const candidate = value as {
    granted: unknown;
    code?: unknown;
    reason?: unknown;
    recorded?: unknown;
  };
  if (candidate.recorded !== undefined && typeof candidate.recorded !== "boolean") {
    throw new TypeError("Approval decision recorded must be Boolean");
  }
  if (candidate.granted === true) {
    if (candidate.code !== "approved") {
      throw new TypeError("Granted approval decisions require code=approved");
    }
    if (candidate.reason !== undefined) {
      throw new TypeError("Granted approval decisions cannot include a reason");
    }
    return {
      granted: true,
      code: "approved",
      ...(candidate.recorded === undefined ? {} : { recorded: candidate.recorded }),
    };
  }
  const code = candidate.code;
  if (
    candidate.granted !== false ||
    (code !== "rejected" && code !== "timeout" && code !== "cancelled" && code !== "unavailable")
  ) {
    throw new TypeError("Rejected approval decisions require a stable rejection code");
  }
  if (typeof candidate.reason !== "string") {
    throw new TypeError("Rejected approval decisions require a reason");
  }
  const reason = candidate.reason;
  if (reason.trim().length === 0 || Array.from(reason).length > 200) {
    throw new TypeError("Approval rejection reason must contain 1 to 200 characters");
  }
  return {
    granted: false,
    code,
    reason,
    ...(candidate.recorded === undefined ? {} : { recorded: candidate.recorded }),
  };
}

function approvalFailure(
  decision: Extract<ApprovalDecision, { granted: false }>,
): Omit<FailureDraft, "status"> {
  const mapping: Record<
    ApprovalRejectionCode,
    { error: string; error_code: string; retryable: boolean }
  > = {
    rejected: {
      error: "Tool approval rejected",
      error_code: "APPROVAL_REJECTED",
      retryable: false,
    },
    timeout: {
      error: "Tool approval timed out",
      error_code: "APPROVAL_TIMEOUT",
      retryable: true,
    },
    cancelled: {
      error: "Tool approval cancelled",
      error_code: "TOOL_CANCELLED",
      retryable: true,
    },
    unavailable: {
      error: "Tool approval unavailable",
      error_code: "APPROVAL_UNAVAILABLE",
      retryable: false,
    },
  };
  return { ...mapping[decision.code], outcome: "not_started" };
}

function approvalDecisionFromEvent(event: StoredKajiEvent): ApprovalDecision | undefined {
  if (event.type === EventType.TOOL_APPROVAL_APPROVED) {
    return { granted: true, code: "approved", recorded: true };
  }
  if (event.type !== EventType.TOOL_APPROVAL_REJECTED) return undefined;
  const code: ApprovalRejectionCode =
    event.error_code === "APPROVAL_TIMEOUT"
      ? "timeout"
      : event.error_code === "TOOL_CANCELLED"
        ? "cancelled"
        : event.error_code === "APPROVAL_UNAVAILABLE"
          ? "unavailable"
          : "rejected";
  return { granted: false, code, reason: event.reason, recorded: true };
}

export class ToolPlanner {
  private readonly executor: ToolExecutor;
  private readonly policy: ToolPolicy | undefined;
  private readonly approvalHandler: TypedApprovalHandler | EventBackedApprovalHandler | undefined;
  private readonly legacyApprovalHandler: LegacyApprovalHandler | undefined;
  readonly approvalCommitter: EventCommitter | undefined;
  private readonly specs: Map<string, ToolSpec>;
  private readonly schemaValidator: ToolSchemaValidator;
  private readonly uuid: () => string;
  private readonly now: () => number;
  readonly executionController: ToolExecutionController;

  /** Canonical emitter for standalone planner usage. */
  static committerEmitter(committer: EventCommitter): EmitFn {
    return bindEmitterToCommitter((event) => committer.commit(event), committer);
  }

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
    this.legacyApprovalHandler =
      typeof opts.approvalHandler === "function" ? opts.approvalHandler : undefined;
    this.approvalHandler =
      typeof opts.approvalHandler === "function" ? undefined : opts.approvalHandler;
    this.approvalCommitter = opts.approvalCommitter;
    this.specs = new Map(
      [...(opts.specs ?? new Map())].map(([name, spec]) => [name, snapshotToolSpec(spec)]),
    );
    this.schemaValidator = new ToolSchemaValidator(this.specs);
    this.uuid = opts.uuid ?? defaultUuid;
    this.now = opts.now ?? Date.now;
    this.executionController =
      opts.executionController ??
      new ToolExecutionController({
        limits: opts.executionLimits,
        ledger: opts.idempotencyLedger,
        monotonicNow: opts.monotonicNow,
        metricsSink: opts.metricsSink,
        traceSink: opts.traceSink,
      });
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
    if (this.approvalCommitter !== undefined && emitterCommitter(emit) !== this.approvalCommitter) {
      throw new TypeError(
        "ToolPlanner emitter committer must match the configured approval committer",
      );
    }
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
        planned.push(await this.preflight(sessionId, resolvedTurnId, call, emit));
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
        draft: {
          status: "failed",
          error: "Tool not permitted",
          error_code: "TOOL_NOT_ALLOWED",
          retryable: false,
          outcome: "not_started",
        },
      };
    }

    if (this.policy?.requiresApproval(call.name, call.spec.risk)) {
      let handlerOwnsRequest = false;
      let storedRequest: StoredKajiEvent | undefined;
      const emitStored = async (event: KajiEvent): Promise<StoredKajiEvent> => {
        const stored = StoredKajiEvent.parse(await emit(event));
        const { sequence: _, ...draft } = stored;
        if (!structurallyEqualJson(draft, event)) {
          throw new TypeError("Approval emitter did not return the event it stored");
        }
        return stored;
      };
      const requestEvent = () =>
        KajiEvent.parse({
          type: EventType.TOOL_APPROVAL_REQUESTED,
          session_id: sessionId,
          turn_id: turnId,
          tool_name: call.name,
          tool_call_id: call.id,
          tool_args: cloneToolExecutionArguments(call.name, call.args),
          risk: call.spec.risk,
          metadata: call.metadata,
        });
      const emitRequest = async (event: KajiEvent = requestEvent()): Promise<StoredKajiEvent> => {
        if (storedRequest !== undefined) {
          throw new TypeError("Approval request was already recorded");
        }
        storedRequest = await emitStored(event);
        return storedRequest;
      };
      const emitDecision = async (decision: ApprovalDecision): Promise<StoredKajiEvent> => {
        const event = decision.granted
          ? KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_APPROVED,
              session_id: sessionId,
              turn_id: turnId,
              tool_name: call.name,
              tool_call_id: call.id,
              metadata: call.metadata,
            })
          : KajiEvent.parse({
              type: EventType.TOOL_APPROVAL_REJECTED,
              session_id: sessionId,
              turn_id: turnId,
              tool_name: call.name,
              tool_call_id: call.id,
              error_code: approvalFailure(decision).error_code,
              reason: decision.reason,
              metadata: call.metadata,
            });
        const stored = await emitStored(event);
        if (storedRequest !== undefined && stored.sequence <= storedRequest.sequence) {
          throw new TypeError("Approval decision must follow its request");
        }
        return stored;
      };

      let decision: ApprovalDecision;
      const handler = this.approvalHandler;
      const legacyHandler = this.legacyApprovalHandler;
      const deadlineMs = Math.min(
        call.context.deadlineMs ?? Number.POSITIVE_INFINITY,
        this.now() + this.executionController.limits.approvalTimeoutMs,
      );
      try {
        handlerOwnsRequest =
          handler !== undefined &&
          "approvalRequestOwner" in handler &&
          handler.approvalRequestOwner === "handler";
        if (!handlerOwnsRequest) await emitRequest();
        if (handler === undefined && legacyHandler === undefined) {
          decision = {
            granted: false,
            code: "unavailable",
            reason: "No approval handler registered",
          };
        } else if (call.context.signal.aborted) {
          decision = {
            granted: false,
            code: "cancelled",
            reason: "Tool approval cancelled",
          };
        } else if (deadlineMs <= this.now()) {
          decision = {
            granted: false,
            code: "timeout",
            reason: "Tool approval timed out",
          };
        } else if (legacyHandler !== undefined) {
          decision = await this.raceApprovalDecision(
            requestLegacyApproval(
              legacyHandler,
              {
                id: call.id,
                name: call.name,
                args: cloneToolExecutionArguments(call.name, call.args),
              },
              call.args,
              call.spec.risk,
            ),
            call.context.signal,
            deadlineMs,
          );
        } else if (handlerOwnsRequest && this.approvalCommitter === undefined) {
          decision = {
            granted: false,
            code: "unavailable",
            reason: "Event approval is not connected to the runtime committer",
          };
        } else if (handler === undefined || this.approvalCommitter === undefined) {
          decision = {
            granted: false,
            code: "unavailable",
            reason: "Approval handler is not connected to the runtime committer",
          };
        } else {
          const context: ApprovalRequestContext = Object.freeze({
            execution: call.context,
            toolName: call.name,
            risk: call.spec.risk,
            arguments: Object.freeze(cloneToolExecutionArguments(call.name, call.args)),
            committer: this.approvalCommitter,
            emit: async (event: KajiEvent) => {
              if (
                event.type !== EventType.TOOL_APPROVAL_REQUESTED ||
                event.session_id !== sessionId ||
                event.turn_id !== turnId ||
                event.tool_name !== call.name ||
                event.tool_call_id !== call.id ||
                event.risk !== call.spec.risk ||
                JSON.stringify(event.tool_args) !== JSON.stringify(call.args)
              ) {
                throw new TypeError("Approval request event does not match the tool call");
              }
              try {
                return await emitRequest(event);
              } catch (cause) {
                throw new ApprovalEventRecordingError({ cause });
              }
            },
            deadlineMs,
          });
          const requested = handler.request(
            {
              id: call.id,
              name: call.name,
              args: cloneToolExecutionArguments(call.name, call.args),
            },
            context,
          );
          decision = normalizeApprovalDecision(
            handlerOwnsRequest
              ? await requested
              : await this.raceApprovalDecision(requested, call.context.signal, deadlineMs),
          );
          if (handlerOwnsRequest && storedRequest === undefined) {
            throw new TypeError(
              "Event-backed approval handler returned before recording its request",
            );
          }
        }
      } catch (error) {
        if (error instanceof ApprovalEventRecordingError) throw error.cause;
        reportError(error);
        decision = {
          granted: false,
          code: "unavailable",
          reason: "Approval handler unavailable",
        };
      }

      if (storedRequest === undefined) await emitRequest();
      const request = storedRequest;
      if (request === undefined) throw new Error("Approval request was not recorded");

      let localDecision: StoredKajiEvent | undefined;
      if (decision.recorded !== true) localDecision = await emitDecision(decision);

      if (this.approvalCommitter !== undefined) {
        let throughSequence =
          localDecision?.sequence ?? (await this.approvalCommitter.store.lastSequence(sessionId));
        let authoritative = await this.authoritativeApprovalDecision(
          sessionId,
          turnId,
          call,
          request.sequence,
          throughSequence,
        );
        if (authoritative === undefined && decision.recorded === true) {
          reportError(new Error("Approval handler claimed a decision that was not recorded"));
          decision = {
            granted: false,
            code: "unavailable",
            reason: "Approval handler unavailable",
          };
          localDecision = await emitDecision(decision);
          throughSequence = localDecision.sequence;
          authoritative = await this.authoritativeApprovalDecision(
            sessionId,
            turnId,
            call,
            request.sequence,
            throughSequence,
          );
        }
        if (authoritative === undefined) {
          throw new Error("Approval decision was not recorded by the approval committer");
        }
        decision = authoritative;
      }

      if (!decision.granted) {
        revokeValidationReceipt(receipt);
        const failure = approvalFailure(decision);
        return {
          status: "terminal",
          call,
          draft: { status: "failed", ...failure },
        };
      }
    }
    return { status: "prepared", call: { ...call, receipt } };
  }

  private async authoritativeApprovalDecision(
    sessionId: string,
    turnId: string,
    call: NormalizedCall,
    requestSequence: number,
    throughSequence: number,
  ): Promise<ApprovalDecision | undefined> {
    if (this.approvalCommitter === undefined || throughSequence <= requestSequence) {
      return undefined;
    }
    const events = await this.approvalCommitter.store.getEvents(sessionId, {
      afterSequence: requestSequence,
      limit: throughSequence - requestSequence,
    });
    for (const event of events.sort((left, right) => left.sequence - right.sequence)) {
      if (event.sequence > throughSequence) break;
      if (
        event.turn_id !== turnId ||
        (event.type !== EventType.TOOL_APPROVAL_APPROVED &&
          event.type !== EventType.TOOL_APPROVAL_REJECTED) ||
        event.tool_call_id !== call.id ||
        event.tool_name !== call.name
      ) {
        continue;
      }
      return approvalDecisionFromEvent(event);
    }
    return undefined;
  }

  private async raceApprovalDecision(
    requested: Promise<ApprovalDecision>,
    signal: AbortSignal,
    deadlineMs: number,
  ): Promise<ApprovalDecision> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let removeAbortListener = () => {};
    const cancelled = new Promise<ApprovalDecision>((resolve) => {
      const finish = () =>
        resolve({
          granted: false,
          code: "cancelled",
          reason: "Tool approval cancelled",
        });
      if (signal.aborted) finish();
      else {
        signal.addEventListener("abort", finish, { once: true });
        removeAbortListener = () => signal.removeEventListener("abort", finish);
      }
    });
    const timeout = new Promise<ApprovalDecision>((resolve) => {
      timer = setTimeout(
        () =>
          resolve({
            granted: false,
            code: "timeout",
            reason: "Tool approval timed out",
          }),
        Math.max(0, deadlineMs - this.now()),
      );
    });
    try {
      return await Promise.race([requested, cancelled, timeout]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      removeAbortListener();
    }
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
    if (outcome.error.cause !== undefined) reportError(outcome.error.cause);
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
