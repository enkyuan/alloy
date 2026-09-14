/** Closed, redaction-safe recovery metadata shared by errors and renderers. */

/** Closed, redaction-safe recovery metadata shared by events and integrations. */
const DOCS = "https://kaji.dev/docs/integrations/recovery-v1";

export type IntegrationRecoveryReason =
  | "github_token_missing"
  | "gmail_grant_missing"
  | "keychain_missing"
  | "keychain_locked"
  | "keychain_corrupt"
  | "keychain_unsupported"
  | "gmail_scope_drift"
  | "policy_rejected"
  | "api_rejected"
  | "transient_read_failed"
  | "rate_limited"
  | "redirect_rejected"
  | "response_limit_exceeded"
  | "github_mutation_unknown"
  | "gmail_mutation_unknown";

function recovery(
  errorCode: string,
  recoveryCode: string,
  anchor: string,
  problem: string,
  cause: string,
  fix: string,
) {
  return Object.freeze({
    errorCode,
    recoveryCode,
    docUrl: `${DOCS}#${anchor}`,
    problem,
    cause,
    fix,
  });
}

export const INTEGRATION_RECOVERY = Object.freeze({
  github_token_missing: recovery(
    "INTEGRATION_AUTH_REQUIRED",
    "CONFIGURE_GITHUB_TOKEN",
    "github-token",
    "GitHub authentication is required.",
    "The configured GitHub token is unavailable.",
    "Set the manifest-declared GitHub token environment variable and retry.",
  ),
  gmail_grant_missing: recovery(
    "INTEGRATION_AUTH_REQUIRED",
    "CONNECT_GMAIL",
    "gmail-grant",
    "Gmail authorization is required.",
    "No Gmail grant exists for this principal.",
    "Use the package-qualified connect command for this runtime and principal, then retry.",
  ),
  keychain_missing: recovery(
    "INTEGRATION_AUTH_ERROR",
    "RESTORE_KEYCHAIN",
    "keychain-missing",
    "The macOS Keychain is unavailable.",
    "The Keychain command could not be found.",
    "Restore `/usr/bin/security` on a supported macOS host and retry.",
  ),
  keychain_locked: recovery(
    "INTEGRATION_AUTH_ERROR",
    "UNLOCK_KEYCHAIN",
    "keychain-locked",
    "The macOS Keychain is locked.",
    "The stored integration grant cannot be read while Keychain is locked.",
    "Unlock the login Keychain and retry.",
  ),
  keychain_corrupt: recovery(
    "INTEGRATION_AUTH_ERROR",
    "RESET_GMAIL_GRANT",
    "keychain-corrupt",
    "The stored Gmail grant is invalid.",
    "The Keychain entry is corrupt or incomplete.",
    "Disconnect Gmail locally, then reconnect with the same principal.",
  ),
  keychain_unsupported: recovery(
    "INTEGRATION_AUTH_ERROR",
    "USE_SUPPORTED_KEYCHAIN",
    "keychain-unsupported",
    "Secure Gmail grant storage is unsupported.",
    "This host cannot provide the required macOS Keychain boundary.",
    "Use a supported macOS host; do not fall back to plaintext storage.",
  ),
  gmail_scope_drift: recovery(
    "INTEGRATION_AUTH_REQUIRED",
    "RECONNECT_GMAIL",
    "gmail-scope-drift",
    "The Gmail grant no longer has the required scopes.",
    "Stored and required OAuth scopes differ.",
    "Use the package-qualified connect command for this runtime and principal, then consent again.",
  ),
  policy_rejected: recovery(
    "INTEGRATION_POLICY_REJECTED",
    "REVIEW_INTEGRATION_POLICY",
    "policy-rejected",
    "The integration request was rejected before dispatch.",
    "A fixed-origin, repository, recipient, or schema policy did not match.",
    "Review the integration allowlist and request shape before retrying.",
  ),
  api_rejected: recovery(
    "INTEGRATION_API_ERROR",
    "REVIEW_PROVIDER_REJECTION",
    "api-rejected",
    "The provider rejected the integration request.",
    "The provider returned a confirmed non-retryable API rejection.",
    "Review the request against the provider response guidance before retrying manually.",
  ),
  transient_read_failed: recovery(
    "INTEGRATION_API_ERROR",
    "RETRY_INTEGRATION_READ",
    "transient-read",
    "The integration read did not complete.",
    "The provider returned a transient failure before any external effect.",
    "Retry the idempotent read with bounded backoff.",
  ),
  rate_limited: recovery(
    "INTEGRATION_RATE_LIMITED",
    "RETRY_AFTER_RATE_LIMIT",
    "rate-limited",
    "The provider rate limit was reached.",
    "The provider confirmed that this request was rate limited.",
    "Reduce parallelism and retry only after the bounded provider delay.",
  ),
  redirect_rejected: recovery(
    "INTEGRATION_REDIRECT_REJECTED",
    "REJECT_PROVIDER_REDIRECT",
    "redirect-rejected",
    "The provider returned a redirect that Kaji will not follow.",
    "Fixed-origin integration requests reject every redirect.",
    "Verify the provider endpoint; do not retry an ambiguous mutation blindly.",
  ),
  response_limit_exceeded: recovery(
    "INTEGRATION_RESPONSE_LIMIT",
    "REDUCE_INTEGRATION_RESPONSE",
    "response-limit",
    "The integration response exceeded a safety bound.",
    "Provider headers or body were malformed or too large.",
    "Narrow the read request; reconcile a mutation before any retry.",
  ),
  github_mutation_unknown: recovery(
    "TOOL_EXECUTION_FAILED",
    "RECONCILE_GITHUB_MUTATION",
    "github-mutation-unknown",
    "The GitHub mutation outcome is unknown.",
    "The connection failed after dispatch without a confirmed provider result.",
    "Reconcile the GitHub issue or comment marker before any manual retry.",
  ),
  gmail_mutation_unknown: recovery(
    "TOOL_EXECUTION_FAILED",
    "RECONCILE_GMAIL_MUTATION",
    "gmail-mutation-unknown",
    "The Gmail mutation outcome is unknown.",
    "The connection failed after dispatch without a confirmed provider result.",
    "Reconcile the Gmail draft key or sent message before any manual retry.",
  ),
}) satisfies Readonly<Record<IntegrationRecoveryReason, ReturnType<typeof recovery>>>;

export interface IntegrationRecoveryFields {
  readonly reason_code: IntegrationRecoveryReason;
  readonly recovery_code: string;
  readonly doc_url: string;
}

export function recoveryForReason(reasonCode: string) {
  const value = INTEGRATION_RECOVERY[reasonCode as IntegrationRecoveryReason];
  if (value === undefined) throw new TypeError("unknown integration recovery reason");
  return value;
}

export function closedRecoveryFields(value: unknown): IntegrationRecoveryFields | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.reason_code !== "string" ||
    typeof candidate.recovery_code !== "string" ||
    typeof candidate.doc_url !== "string"
  ) {
    return undefined;
  }
  const recovery = INTEGRATION_RECOVERY[candidate.reason_code as IntegrationRecoveryReason];
  if (
    recovery === undefined ||
    recovery.recoveryCode !== candidate.recovery_code ||
    recovery.docUrl !== candidate.doc_url ||
    ("error_code" in candidate && recovery.errorCode !== candidate.error_code)
  ) {
    return undefined;
  }
  return Object.freeze({
    reason_code: candidate.reason_code as IntegrationRecoveryReason,
    recovery_code: candidate.recovery_code,
    doc_url: candidate.doc_url,
  });
}

export function closedTransportFailureFields(value: unknown) {
  if (typeof value !== "object" || value === null) return undefined;
  const candidate = value as Record<string, unknown>;
  const fields = closedRecoveryFields(candidate);
  if (fields === undefined || typeof candidate.error_code !== "string") return undefined;
  const recovery = INTEGRATION_RECOVERY[fields.reason_code];
  if (candidate.error_code !== recovery.errorCode) return undefined;
  return Object.freeze({ error_code: recovery.errorCode, ...fields });
}

export function isClosedRecoveryTuple(
  reasonCode: unknown,
  recoveryCode: unknown,
  docUrl: unknown,
  errorCode?: unknown,
): boolean {
  if (reasonCode === undefined && recoveryCode === undefined && docUrl === undefined) return true;
  return (
    closedRecoveryFields({
      error_code: errorCode,
      reason_code: reasonCode,
      recovery_code: recoveryCode,
      doc_url: docUrl,
    }) !== undefined
  );
}
