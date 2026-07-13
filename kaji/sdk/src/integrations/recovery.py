"""Closed, redaction-safe integration recovery metadata."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class IntegrationRecovery:
    error_code: str
    recovery_code: str
    doc_url: str
    problem: str
    cause: str
    fix: str


_DOCS = "https://kaji.dev/docs/integrations/recovery-v1"


def _recovery(
    error_code: str,
    recovery_code: str,
    anchor: str,
    problem: str,
    cause: str,
    fix: str,
) -> IntegrationRecovery:
    return IntegrationRecovery(
        error_code=error_code,
        recovery_code=recovery_code,
        doc_url=f"{_DOCS}#{anchor}",
        problem=problem,
        cause=cause,
        fix=fix,
    )


INTEGRATION_RECOVERY: Final = MappingProxyType(
    {
        "github_token_missing": _recovery(
            "INTEGRATION_AUTH_REQUIRED",
            "CONFIGURE_GITHUB_TOKEN",
            "github-token",
            "GitHub authentication is required.",
            "The configured GitHub token is unavailable.",
            "Set the manifest-declared GitHub token environment variable and retry.",
        ),
        "gmail_grant_missing": _recovery(
            "INTEGRATION_AUTH_REQUIRED",
            "CONNECT_GMAIL",
            "gmail-grant",
            "Gmail authorization is required.",
            "No Gmail grant exists for this principal.",
            "Use the package-qualified connect command for this runtime and principal, then retry.",
        ),
        "keychain_missing": _recovery(
            "INTEGRATION_AUTH_ERROR",
            "RESTORE_KEYCHAIN",
            "keychain-missing",
            "The macOS Keychain is unavailable.",
            "The Keychain command could not be found.",
            "Restore `/usr/bin/security` on a supported macOS host and retry.",
        ),
        "keychain_locked": _recovery(
            "INTEGRATION_AUTH_ERROR",
            "UNLOCK_KEYCHAIN",
            "keychain-locked",
            "The macOS Keychain is locked.",
            "The stored integration grant cannot be read while Keychain is locked.",
            "Unlock the login Keychain and retry.",
        ),
        "keychain_corrupt": _recovery(
            "INTEGRATION_AUTH_ERROR",
            "RESET_GMAIL_GRANT",
            "keychain-corrupt",
            "The stored Gmail grant is invalid.",
            "The Keychain entry is corrupt or incomplete.",
            "Disconnect Gmail locally, then reconnect with the same principal.",
        ),
        "keychain_unsupported": _recovery(
            "INTEGRATION_AUTH_ERROR",
            "USE_SUPPORTED_KEYCHAIN",
            "keychain-unsupported",
            "Secure Gmail grant storage is unsupported.",
            "This host cannot provide the required macOS Keychain boundary.",
            "Use a supported macOS host; do not fall back to plaintext storage.",
        ),
        "gmail_scope_drift": _recovery(
            "INTEGRATION_AUTH_REQUIRED",
            "RECONNECT_GMAIL",
            "gmail-scope-drift",
            "The Gmail grant no longer has the required scopes.",
            "Stored and required OAuth scopes differ.",
            "Use the package-qualified connect command for this runtime and principal, then consent again.",
        ),
        "policy_rejected": _recovery(
            "INTEGRATION_POLICY_REJECTED",
            "REVIEW_INTEGRATION_POLICY",
            "policy-rejected",
            "The integration request was rejected before dispatch.",
            "A fixed-origin, repository, recipient, or schema policy did not match.",
            "Review the integration allowlist and request shape before retrying.",
        ),
        "api_rejected": _recovery(
            "INTEGRATION_API_ERROR",
            "REVIEW_PROVIDER_REJECTION",
            "api-rejected",
            "The provider rejected the integration request.",
            "The provider returned a confirmed non-retryable API rejection.",
            "Review the request against the provider response guidance before retrying manually.",
        ),
        "transient_read_failed": _recovery(
            "INTEGRATION_API_ERROR",
            "RETRY_INTEGRATION_READ",
            "transient-read",
            "The integration read did not complete.",
            "The provider returned a transient failure before any external effect.",
            "Retry the idempotent read with bounded backoff.",
        ),
        "rate_limited": _recovery(
            "INTEGRATION_RATE_LIMITED",
            "RETRY_AFTER_RATE_LIMIT",
            "rate-limited",
            "The provider rate limit was reached.",
            "The provider confirmed that this request was rate limited.",
            "Reduce parallelism and retry only after the bounded provider delay.",
        ),
        "redirect_rejected": _recovery(
            "INTEGRATION_REDIRECT_REJECTED",
            "REJECT_PROVIDER_REDIRECT",
            "redirect-rejected",
            "The provider returned a redirect that Kaji will not follow.",
            "Fixed-origin integration requests reject every redirect.",
            "Verify the provider endpoint; do not retry an ambiguous mutation blindly.",
        ),
        "response_limit_exceeded": _recovery(
            "INTEGRATION_RESPONSE_LIMIT",
            "REDUCE_INTEGRATION_RESPONSE",
            "response-limit",
            "The integration response exceeded a safety bound.",
            "Provider headers or body were malformed or too large.",
            "Narrow the read request; reconcile a mutation before any retry.",
        ),
        "github_mutation_unknown": _recovery(
            "TOOL_EXECUTION_FAILED",
            "RECONCILE_GITHUB_MUTATION",
            "github-mutation-unknown",
            "The GitHub mutation outcome is unknown.",
            "The connection failed after dispatch without a confirmed provider result.",
            "Reconcile the GitHub issue or comment marker before any manual retry.",
        ),
        "gmail_mutation_unknown": _recovery(
            "TOOL_EXECUTION_FAILED",
            "RECONCILE_GMAIL_MUTATION",
            "gmail-mutation-unknown",
            "The Gmail mutation outcome is unknown.",
            "The connection failed after dispatch without a confirmed provider result.",
            "Reconcile the Gmail draft key or sent message before any manual retry.",
        ),
    }
)


def recovery_for_reason(reason_code: str) -> IntegrationRecovery:
    """Return one contract-owned recovery row or fail closed."""
    try:
        return INTEGRATION_RECOVERY[reason_code]
    except KeyError:
        raise ValueError("unknown integration recovery reason") from None


def closed_recovery_fields(value: object) -> dict[str, str]:
    """Project a complete valid recovery tuple from an untrusted exception."""
    reason_code = getattr(value, "reason_code", None)
    recovery_code = getattr(value, "recovery_code", None)
    doc_url = getattr(value, "doc_url", None)
    if (
        not isinstance(reason_code, str)
        or not isinstance(recovery_code, str)
        or not isinstance(doc_url, str)
    ):
        return {}
    recovery = INTEGRATION_RECOVERY.get(reason_code)
    if recovery is None or (recovery.recovery_code, recovery.doc_url) != (
        recovery_code,
        doc_url,
    ):
        return {}
    error_code = getattr(value, "error_code", None)
    if error_code is not None and (
        not isinstance(error_code, str) or error_code != recovery.error_code
    ):
        return {}
    return {
        "reason_code": reason_code,
        "recovery_code": recovery_code,
        "doc_url": doc_url,
    }


def closed_transport_failure_fields(value: object) -> dict[str, str]:
    """Preserve an ordinary failure code only for one exact canonical row."""
    fields = closed_recovery_fields(value)
    error_code = getattr(value, "error_code", None)
    if not fields or not isinstance(error_code, str):
        return {}
    recovery = INTEGRATION_RECOVERY[fields["reason_code"]]
    if error_code != recovery.error_code:
        return {}
    return {"error_code": recovery.error_code, **fields}


def is_closed_recovery_tuple(
    reason_code: str | None,
    recovery_code: str | None,
    doc_url: str | None,
    error_code: str | None = None,
) -> bool:
    """Validate all-or-none durable recovery metadata."""
    if reason_code is recovery_code is doc_url is None:
        return True
    if (
        not isinstance(reason_code, str)
        or not isinstance(recovery_code, str)
        or not isinstance(doc_url, str)
    ):
        return False
    recovery = INTEGRATION_RECOVERY.get(reason_code)
    return recovery is not None and (
        recovery.error_code,
        recovery.recovery_code,
        recovery.doc_url,
    ) == (error_code, recovery_code, doc_url)
