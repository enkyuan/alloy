"""Redaction-safe errors owned by the model-provider boundary."""

from __future__ import annotations

from typing import Literal, TypedDict

import httpx

__all__ = [
    "NormalizedProviderError",
    "ProviderAPIError",
    "ProviderConfigError",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderOutputLimitError",
    "ProviderRateLimitedError",
    "classify_http_error",
    "normalize_provider_error",
    "provider_error_from_exception",
]


ProviderOutputDimension = Literal[
    "text",
    "tool_arguments",
    "total_response",
    "tool_calls",
]


class ProviderOutputLimitError(RuntimeError):
    """A provider response exceeded one closed, payload-free dimension."""

    code = "PROVIDER_OUTPUT_LIMIT"
    phase = "provider_stream"
    retryable = False
    outcome = "unknown"

    def __init__(self, dimension: ProviderOutputDimension, limit: int) -> None:
        if dimension not in {
            "text",
            "tool_arguments",
            "total_response",
            "tool_calls",
        }:
            raise ValueError("unknown provider output dimension")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("provider output limit must be a positive integer")
        self.dimension = dimension
        self.limit = limit
        unit = "calls" if dimension == "tool_calls" else "bytes"
        super().__init__(
            f"Provider output exceeded {dimension} limit of {limit} {unit}"
        )


class NormalizedProviderError(TypedDict):
    """Stable semantic provider failure shape used at SDK boundaries."""

    type: Literal["api", "auth", "config", "network", "rate_limit"]
    code: Literal[
        "PROVIDER_API_ERROR",
        "PROVIDER_AUTH_ERROR",
        "PROVIDER_CONFIG_ERROR",
        "PROVIDER_NETWORK_ERROR",
        "PROVIDER_RATE_LIMITED",
    ]
    service: str
    action: str
    status: int | None
    retryable: bool


class ProviderError(Exception):
    """Base exception for model-provider failures.

    Only stable, caller-safe metadata is retained. Vendor exceptions and
    response bodies stay outside this public boundary.
    """

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "request",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.action = action
        self.status_code = status_code


class ProviderConfigError(ProviderError):
    """Raised when a provider is missing required configuration."""

    def __init__(self, message: str, *, service: str = "provider") -> None:
        super().__init__(message, service=service, action="configure")


class ProviderAPIError(ProviderError):
    """Raised when a provider API returns an unexpected response."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "api call",
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            service=service,
            action=action,
            status_code=status_code,
        )


class ProviderConnectionError(ProviderError):
    """Raised when the connection to a provider fails."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "connect",
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            service=service,
            action=action,
            status_code=status_code,
        )


class ProviderRateLimitedError(ProviderError):
    """Raised when a provider rejects a request because of rate limits."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "api call",
    ) -> None:
        super().__init__(
            message,
            service=service,
            action=action,
            status_code=429,
        )


def classify_http_error(
    *,
    service: str,
    action: str,
    status_code: int,
) -> ProviderError:
    """Map a provider HTTP status to a redacted provider-owned error."""
    message = f"{service} {action} failed with status {status_code}"
    if status_code == 429:
        return ProviderRateLimitedError(
            message,
            service=service,
            action=action,
        )
    return ProviderAPIError(
        message,
        service=service,
        action=action,
        status_code=status_code,
    )


def _extract_status_code(error: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value

    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return (
        response_status
        if isinstance(response_status, int) and not isinstance(response_status, bool)
        else None
    )


def _is_network_error(error: Exception) -> bool:
    vendor_type_names = {
        "APIConnectionError",
        "APIConnectionTimeoutError",
        "APITimeoutError",
    }
    return isinstance(
        error, (ConnectionError, OSError, TimeoutError, httpx.RequestError)
    ) or any(cls.__name__ in vendor_type_names for cls in type(error).__mro__)


def provider_error_from_exception(
    *,
    service: str,
    action: str,
    error: Exception,
) -> ProviderError:
    """Convert a vendor exception into a fresh, payload-free provider error."""
    status_code = _extract_status_code(error)
    if isinstance(error, ProviderConfigError):
        return ProviderConfigError(
            f"{service} configuration failed",
            service=service,
        )
    if isinstance(error, ProviderConnectionError):
        return ProviderConnectionError(
            f"{service} {action} failed due to a network error",
            service=service,
            action=action,
            status_code=status_code,
        )
    if isinstance(error, ProviderRateLimitedError):
        return ProviderRateLimitedError(
            f"{service} {action} rate limited",
            service=service,
            action=action,
        )
    if isinstance(error, ProviderError):
        return ProviderAPIError(
            f"{service} {action} failed",
            service=service,
            action=action,
            status_code=status_code,
        )
    if status_code is not None:
        return classify_http_error(
            service=service,
            action=action,
            status_code=status_code,
        )
    if _is_network_error(error):
        return ProviderConnectionError(
            f"{service} {action} failed due to a network error",
            service=service,
            action=action,
        )
    return ProviderAPIError(
        f"{service} {action} failed",
        service=service,
        action=action,
    )


def normalize_provider_error(error: ProviderError) -> NormalizedProviderError:
    """Return provider-neutral classification without exposing private messages."""
    status = error.status_code
    error_type: Literal["api", "auth", "config", "network", "rate_limit"]
    code: Literal[
        "PROVIDER_API_ERROR",
        "PROVIDER_AUTH_ERROR",
        "PROVIDER_CONFIG_ERROR",
        "PROVIDER_NETWORK_ERROR",
        "PROVIDER_RATE_LIMITED",
    ]
    if isinstance(error, ProviderConfigError):
        error_type, code, retryable = "config", "PROVIDER_CONFIG_ERROR", False
    elif isinstance(error, ProviderConnectionError):
        error_type, code, retryable = "network", "PROVIDER_NETWORK_ERROR", True
    elif isinstance(error, ProviderRateLimitedError) or status == 429:
        error_type, code, retryable = "rate_limit", "PROVIDER_RATE_LIMITED", True
    elif status in (401, 403):
        error_type, code, retryable = "auth", "PROVIDER_AUTH_ERROR", False
    else:
        error_type, code = "api", "PROVIDER_API_ERROR"
        retryable = status is not None and status >= 500
    return {
        "type": error_type,
        "code": code,
        "service": error.service,
        "action": error.action,
        "status": status,
        "retryable": retryable,
    }
