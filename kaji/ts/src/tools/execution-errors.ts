export type ToolFailureOutcome = "not_started" | "failed" | "unknown";

export interface ToolFailureFields {
  readonly error_code: string;
  readonly retryable: boolean;
  readonly outcome: ToolFailureOutcome;
}

/** Stable public tool failure with an optional private tracing cause. */
export class ToolExecutionError extends Error implements ToolFailureFields {
  constructor(
    message: string,
    readonly error_code: string,
    readonly retryable: boolean,
    readonly outcome: ToolFailureOutcome,
    options: ErrorOptions = {},
  ) {
    super(message, options);
    this.name = "ToolExecutionError";
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
  const snapshot = new ToolExecutionError(
    error.message,
    error.error_code,
    error.retryable,
    error.outcome,
    { cause: error.cause },
  );
  snapshot.name = error.name;
  return Object.freeze(snapshot);
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

export function toolExecutionFailed(cause: unknown): ToolExecutionError {
  return new ToolExecutionError("Tool execution failed", "TOOL_EXECUTION_FAILED", false, "failed", {
    cause,
  });
}

export function toolStartRecordFailed(cause: unknown): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution did not start",
    "TOOL_START_RECORD_FAILED",
    true,
    "not_started",
    { cause },
  );
}

export function toolExecutionUnknown(cause: unknown): ToolExecutionError {
  return new ToolExecutionError(
    "Tool execution failed with an unknown outcome",
    "TOOL_EXECUTION_FAILED",
    false,
    "unknown",
    { cause },
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
    { cause },
  );
}
