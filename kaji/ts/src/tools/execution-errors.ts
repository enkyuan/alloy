import {
  closedRecoveryFields,
  closedTransportFailureFields,
  type IntegrationRecoveryFields,
  type IntegrationRecoveryReason,
} from "@/contracts/integration-recovery";

export type ToolFailureOutcome = "not_started" | "failed" | "unknown";

export interface ToolFailureFields {
  readonly error_code: string;
  readonly retryable: boolean;
  readonly outcome: ToolFailureOutcome;
  readonly reason_code?: IntegrationRecoveryReason;
  readonly recovery_code?: string;
  readonly doc_url?: string;
}

const TOOL_EXECUTION_ERROR_BRAND = Symbol.for("@kaji/sdk.ToolExecutionError.v1");

function nativeInstanceOf(constructor: Function, value: unknown): boolean {
  return Function.prototype[Symbol.hasInstance].call(constructor, value) as boolean;
}

/** Stable public tool failure without retaining the originating exception. */
export class ToolExecutionError extends Error implements ToolFailureFields {
  static [Symbol.hasInstance](value: unknown): boolean {
    if (this !== ToolExecutionError) return nativeInstanceOf(this, value);
    return (
      nativeInstanceOf(this, value) ||
      (value instanceof Error && Reflect.get(value, TOOL_EXECUTION_ERROR_BRAND) === true)
    );
  }

  constructor(
    message: string,
    readonly error_code: string,
    readonly retryable: boolean,
    readonly outcome: ToolFailureOutcome,
    recovery?: IntegrationRecoveryFields,
  ) {
    super(message);
    this.name = "ToolExecutionError";
    Object.defineProperty(this, TOOL_EXECUTION_ERROR_BRAND, { value: true });
    if (recovery !== undefined) {
      this.reason_code = recovery.reason_code;
      this.recovery_code = recovery.recovery_code;
      this.doc_url = recovery.doc_url;
    }
  }

  readonly reason_code?: IntegrationRecoveryReason;
  readonly recovery_code?: string;
  readonly doc_url?: string;
}

export class DurableToolResultTombstone extends ToolExecutionError {
  constructor(
    readonly subject: DurableJsonSubject,
    readonly durableCode: "INVALID_DURABLE_VALUE" | "EVENT_PAYLOAD_TOO_LARGE",
  ) {
    super("Invalid durable tool result", durableCode, false, "unknown");
    this.name = "DurableToolResultTombstone";
  }
}

export class IdempotencyCapacityError extends ToolExecutionError {
  constructor() {
    super(
      "Tool execution idempotency capacity is exhausted",
      "IDEMPOTENCY_CAPACITY_EXCEEDED",
      true,
      "not_started",
    );
    this.name = "IdempotencyCapacityError";
  }
}

export class IdempotencyConflictError extends ToolExecutionError {
  constructor() {
    super(
      "Tool call identity was reused for a different invocation",
      "IDEMPOTENCY_CONFLICT",
      false,
      "not_started",
    );
    this.name = "IdempotencyConflictError";
  }
}

export function snapshotToolExecutionError(error: ToolExecutionError): ToolExecutionError {
  if (error instanceof DurableToolResultTombstone) {
    return Object.freeze(new DurableToolResultTombstone(error.subject, error.durableCode));
  }
  const snapshot = new ToolExecutionError(
    error.message,
    error.error_code,
    error.retryable,
    error.outcome,
    closedRecoveryFields(error),
  );
  snapshot.name = error.name;
  return Object.freeze(snapshot);
}

export function invalidToolResult(): ToolExecutionError {
  return new ToolExecutionError("Invalid tool result", "INVALID_TOOL_RESULT", false, "unknown");
}

export function durableToolResultTombstone(
  error: InvalidDurableValueError | DurableJsonLimitError,
): DurableToolResultTombstone {
  return new DurableToolResultTombstone(error.subject, error.code);
}

export function publicToolExecutionError(error: ToolExecutionError): ToolExecutionError {
  const subject = (error as ToolExecutionError & { readonly subject?: unknown }).subject;
  if (
    subject === "tool_result" &&
    (error.error_code === "INVALID_DURABLE_VALUE" || error.error_code === "EVENT_PAYLOAD_TOO_LARGE")
  ) {
    return invalidToolResult();
  }
  return error;
}

export function toolCancelled(outcome: "not_started" | "unknown"): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution cancelled",
    "TOOL_CANCELLED",
    outcome === "not_started",
    outcome,
  );
}

export function toolTimedOut(outcome: "not_started" | "unknown"): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution timed out",
    "TOOL_TIMEOUT",
    outcome === "not_started",
    outcome,
  );
}

export function toolExecutionFailed(_cause: unknown): ToolExecutionError {
  return new ToolExecutionError("Tool execution failed", "TOOL_EXECUTION_FAILED", false, "failed");
}

export function toolStartRecordFailed(_cause: unknown): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution did not start",
    "TOOL_START_RECORD_FAILED",
    true,
    "not_started",
  );
}

export function toolExecutionUnknown(cause: unknown): ToolExecutionError {
  const transport = closedTransportFailureFields(cause);
  return new ToolExecutionError(
    "Tool execution failed with an unknown outcome",
    transport?.error_code ?? "TOOL_EXECUTION_FAILED",
    false,
    "unknown",
    transport,
  );
}

/** Preserve only an explicitly typed post-start certainty, never its message. */
export function normalizeStartedToolFailure(cause: unknown): ToolExecutionError {
  if (
    !(cause instanceof ToolExecutionError) ||
    typeof cause.error_code !== "string" ||
    !/^[A-Z][A-Z0-9_]{0,63}$/.test(cause.error_code) ||
    typeof cause.retryable !== "boolean" ||
    !["not_started", "failed", "unknown"].includes(cause.outcome)
  ) {
    return toolExecutionUnknown(cause);
  }
  if (cause.outcome === "not_started") return toolExecutionUnknown(cause);
  return new ToolExecutionError(
    cause.outcome === "failed"
      ? "Tool execution failed"
      : "Tool execution failed with an unknown outcome",
    cause.error_code,
    cause.outcome === "failed" && cause.retryable,
    cause.outcome,
    closedRecoveryFields(cause),
  );
}
import {
  DurableJsonLimitError,
  InvalidDurableValueError,
  type DurableJsonSubject,
} from "@/events/errors";
