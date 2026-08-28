import { ToolExecutionError } from "@/tools/execution-errors";
import {
  recoveryForReason,
  type IntegrationRecoveryReason,
} from "@/contracts/integration-recovery";

type CertifiedFailureKind =
  | "api"
  | "auth_required"
  | "auth"
  | "rate_limited"
  | "transient_read"
  | "policy";

function certified(
  kind: CertifiedFailureKind,
  reasonCode: IntegrationRecoveryReason,
  retryable: boolean,
) {
  return Object.freeze({ kind, recovery: recoveryForReason(reasonCode), retryable });
}

const CERTIFIED_FAILURES = Object.freeze({
  api_rejected: certified("api", "api_rejected", false),
  github_token_missing: certified("auth_required", "github_token_missing", false),
  gmail_grant_missing: certified("auth_required", "gmail_grant_missing", false),
  gmail_scope_drift: certified("auth_required", "gmail_scope_drift", false),
  keychain_missing: certified("auth", "keychain_missing", false),
  keychain_locked: certified("auth", "keychain_locked", false),
  keychain_corrupt: certified("auth", "keychain_corrupt", false),
  keychain_unsupported: certified("auth", "keychain_unsupported", false),
  rate_limited: certified("rate_limited", "rate_limited", true),
  transient_read_failed: certified("transient_read", "transient_read_failed", true),
  policy_rejected: certified("policy", "policy_rejected", false),
} as const);

type CertifiedIntegrationReason = keyof typeof CERTIFIED_FAILURES;

function certifiedFailure(reasonCode: string) {
  const failure = CERTIFIED_FAILURES[reasonCode as CertifiedIntegrationReason];
  if (failure === undefined) throw new TypeError("uncertified integration failure reason");
  return failure;
}

function constructorKind(constructor: Function): string | undefined {
  if (constructor === IntegrationExecutionError) return "api";
  if (constructor === IntegrationAuthRequiredError) return "auth_required";
  if (constructor === IntegrationAuthError) return "auth";
  if (constructor === IntegrationRateLimitedError) return "rate_limited";
  if (constructor === IntegrationTransientReadError) return "transient_read";
  if (constructor === IntegrationPolicyError) return "policy";
  return undefined;
}

export class IntegrationExecutionError extends ToolExecutionError {
  constructor(reasonCode: "api_rejected");
  constructor(reasonCode: CertifiedIntegrationReason) {
    const failure = certifiedFailure(reasonCode);
    if (failure.kind !== constructorKind(new.target)) {
      throw new TypeError("integration failure reason is not certified for this error class");
    }
    const { recovery } = failure;
    super("Tool execution failed", recovery.errorCode, failure.retryable, "failed", {
      reason_code: reasonCode,
      recovery_code: recovery.recoveryCode,
      doc_url: recovery.docUrl,
    });
    this.name = "IntegrationExecutionError";
  }
}

export class IntegrationAuthRequiredError extends IntegrationExecutionError {
  constructor(
    reasonCode: Extract<
      IntegrationRecoveryReason,
      "github_token_missing" | "gmail_grant_missing" | "gmail_scope_drift"
    >,
  ) {
    super(reasonCode as never);
    this.name = "IntegrationAuthRequiredError";
  }
}

export class IntegrationAuthError extends IntegrationExecutionError {
  constructor(
    reasonCode: Extract<
      IntegrationRecoveryReason,
      "keychain_missing" | "keychain_locked" | "keychain_corrupt" | "keychain_unsupported"
    >,
  ) {
    super(reasonCode as never);
    this.name = "IntegrationAuthError";
  }
}

export class IntegrationRateLimitedError extends IntegrationExecutionError {
  constructor() {
    super("rate_limited" as never);
    this.name = "IntegrationRateLimitedError";
  }
}

export class IntegrationTransientReadError extends IntegrationExecutionError {
  constructor() {
    super("transient_read_failed" as never);
    this.name = "IntegrationTransientReadError";
  }
}

export class IntegrationPolicyError extends IntegrationExecutionError {
  constructor() {
    super("policy_rejected" as never);
    this.name = "IntegrationPolicyError";
  }
}

export class IntegrationTransportError extends Error {
  readonly reason_code?: IntegrationRecoveryReason;
  readonly recovery_code?: string;
  readonly doc_url?: string;

  constructor(
    readonly error_code: string,
    reasonCode?: IntegrationRecoveryReason,
  ) {
    super("Integration transport failed");
    this.name = "IntegrationTransportError";
    if (reasonCode !== undefined) {
      const recovery = recoveryForReason(reasonCode);
      if (recovery.errorCode !== error_code) {
        throw new TypeError("integration recovery reason does not match error code");
      }
      this.reason_code = reasonCode;
      this.recovery_code = recovery.recoveryCode;
      this.doc_url = recovery.docUrl;
    }
  }
}
