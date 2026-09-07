"""Stable integration failures that never retain provider details."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from kaji.integrations.recovery import IntegrationRecovery, recovery_for_reason
from kaji.runtime.tools.execution import ToolExecutionError


def _certified(
    kind: str, reason_code: str, retryable: bool
) -> tuple[str, IntegrationRecovery, bool]:
    return kind, recovery_for_reason(reason_code), retryable


_CERTIFIED_FAILURES = MappingProxyType(
    {
        "api_rejected": _certified("api", "api_rejected", False),
        "github_token_missing": _certified(
            "auth_required", "github_token_missing", False
        ),
        "gmail_grant_missing": _certified(
            "auth_required", "gmail_grant_missing", False
        ),
        "gmail_scope_drift": _certified("auth_required", "gmail_scope_drift", False),
        "keychain_missing": _certified("auth", "keychain_missing", False),
        "keychain_locked": _certified("auth", "keychain_locked", False),
        "keychain_corrupt": _certified("auth", "keychain_corrupt", False),
        "keychain_unsupported": _certified("auth", "keychain_unsupported", False),
        "rate_limited": _certified("rate_limited", "rate_limited", True),
        "transient_read_failed": _certified(
            "transient_read", "transient_read_failed", True
        ),
        "policy_rejected": _certified("policy", "policy_rejected", False),
    }
)


class IntegrationExecutionError(ToolExecutionError):
    """A certified integration failure known to have no external effect."""

    outcome: Literal["failed"] = "failed"

    def __init__(self, reason_code: str) -> None:
        failure = _CERTIFIED_FAILURES.get(reason_code)
        if failure is None:
            raise ValueError("uncertified integration failure reason")
        kind, recovery, retryable = failure
        if kind != _constructor_kind(type(self)):
            raise ValueError(
                "integration failure reason is not certified for this error class"
            )
        self.error_code = recovery.error_code
        self.retryable = retryable
        self.reason_code = reason_code
        self.recovery_code = recovery.recovery_code
        self.doc_url = recovery.doc_url
        super().__init__()


class IntegrationAuthRequiredError(IntegrationExecutionError):
    def __init__(
        self,
        reason_code: Literal[
            "github_token_missing", "gmail_grant_missing", "gmail_scope_drift"
        ],
    ) -> None:
        super().__init__(reason_code)


class IntegrationAuthError(IntegrationExecutionError):
    def __init__(
        self,
        reason_code: Literal[
            "keychain_missing",
            "keychain_locked",
            "keychain_corrupt",
            "keychain_unsupported",
        ],
    ) -> None:
        super().__init__(reason_code)


class IntegrationRateLimitedError(IntegrationExecutionError):
    def __init__(self) -> None:
        super().__init__("rate_limited")


class IntegrationTransientReadError(IntegrationExecutionError):
    def __init__(self) -> None:
        super().__init__("transient_read_failed")


class IntegrationPolicyError(IntegrationExecutionError):
    def __init__(self) -> None:
        super().__init__("policy_rejected")


def _constructor_kind(constructor: type[IntegrationExecutionError]) -> str | None:
    return {
        IntegrationExecutionError: "api",
        IntegrationAuthRequiredError: "auth_required",
        IntegrationAuthError: "auth",
        IntegrationRateLimitedError: "rate_limited",
        IntegrationTransientReadError: "transient_read",
        IntegrationPolicyError: "policy",
    }.get(constructor)


class IntegrationTransportError(RuntimeError):
    """A redacted, non-certified transport failure with optional safe recovery."""

    def __init__(self, error_code: str, reason_code: str | None = None) -> None:
        self.error_code = error_code
        if reason_code is not None:
            recovery = recovery_for_reason(reason_code)
            if recovery.error_code != error_code:
                raise ValueError(
                    "integration recovery reason does not match error code"
                )
            self.reason_code = reason_code
            self.recovery_code = recovery.recovery_code
            self.doc_url = recovery.doc_url
        super().__init__("Integration transport failed")
