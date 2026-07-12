/** Whole-turn execution limits and stable timeout errors. */

export type TurnPhase = "queue" | "provider_open" | "provider_stream" | "approval" | "tool";
export type TurnOutcome = "not_started" | "failed" | "unknown";

export interface TurnExecutionLimits {
  readonly turnTimeoutMs: number;
  readonly providerCancellationGraceMs: number;
  readonly providerTextMaxBytes: number;
  readonly providerToolArgumentsMaxBytes: number;
  readonly providerResponseMaxBytes: number;
  readonly providerToolCallsMax: number;
}

export const DEFAULT_TURN_EXECUTION_LIMITS: Readonly<TurnExecutionLimits> = Object.freeze({
  turnTimeoutMs: 120_000,
  providerCancellationGraceMs: 5_000,
  providerTextMaxBytes: 262_144,
  providerToolArgumentsMaxBytes: 65_536,
  providerResponseMaxBytes: 524_288,
  providerToolCallsMax: 64,
});

export function resolveTurnExecutionLimits(
  overrides: Partial<TurnExecutionLimits> = {},
): Readonly<TurnExecutionLimits> {
  const limits = { ...DEFAULT_TURN_EXECUTION_LIMITS, ...overrides };
  for (const [name, value] of Object.entries(limits)) {
    if (!Number.isInteger(value) || value < 1) {
      throw new RangeError(`${name} must be a positive integer`);
    }
  }
  return Object.freeze(limits);
}

export class TurnTimeoutError extends Error {
  readonly code = "TURN_TIMEOUT" as const;

  constructor(
    readonly phase: TurnPhase,
    readonly retryable: boolean,
    readonly outcome: TurnOutcome,
  ) {
    super(`Turn deadline exceeded during ${phase}`);
    if (typeof retryable !== "boolean") throw new TypeError("retryable must be a boolean");
    if (
      !(["queue", "provider_open", "provider_stream", "approval", "tool"] as const).includes(phase)
    ) {
      throw new TypeError("phase must be a supported turn phase");
    }
    if (!(["not_started", "failed", "unknown"] as const).includes(outcome)) {
      throw new TypeError("outcome must be a supported turn outcome");
    }
    this.name = "TurnTimeoutError";
  }
}

export class ProviderCancellationContractViolation extends Error {
  readonly code = "PROVIDER_CANCELLATION_CONTRACT_VIOLATION" as const;
  readonly retryable = false;
  readonly outcome = "unknown" as const;

  constructor(
    readonly phase: Extract<TurnPhase, "provider_open" | "provider_stream"> = "provider_stream",
  ) {
    super("Provider did not stop after cancellation");
    this.name = "ProviderCancellationContractViolation";
  }
}

interface ProviderViolationDetails {
  readonly settlement: Promise<void>;
}

const PROVIDER_VIOLATION_DETAILS = new WeakMap<
  ProviderCancellationContractViolation,
  ProviderViolationDetails
>();

export function attachProviderViolationSettlement(
  error: ProviderCancellationContractViolation,
  settlement: Promise<void>,
): ProviderCancellationContractViolation {
  PROVIDER_VIOLATION_DETAILS.set(error, { settlement });
  return error;
}

export function providerViolationSettlement(
  error: ProviderCancellationContractViolation,
): Promise<void> | undefined {
  return PROVIDER_VIOLATION_DETAILS.get(error)?.settlement;
}
