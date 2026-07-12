"""Errors for model providers.

The foundational ``Service*`` errors and HTTP-classification helpers live in
``kaji.core.errors`` (so ``core`` need not depend upward on ``providers``)
and are re-exported here for backwards compatibility. This module adds the
LLM-provider-specific subclasses on top.
"""

from __future__ import annotations

import httpx
from typing import Literal, TypedDict

from kaji.core.errors import (
    ServiceAPIError,
    ServiceAuthError,
    ServiceError,
    ServiceNetworkError,
    ServiceRateLimitError,
    service_error_to_detail,
    service_error_to_http_status,
)

ServiceErrorToDetail = service_error_to_detail
ServiceErrorToHTTPStatus = service_error_to_http_status

__all__ = [
    "ClassifyHTTPError",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAPIError",
    "ProviderConnectionError",
    "ProviderOutputLimitError",
    "ServiceAPIError",
    "ServiceAuthError",
    "ServiceError",
    "ServiceErrorToDetail",
    "ServiceErrorToHTTPStatus",
    "ServiceNetworkError",
    "ServiceRateLimitError",
    "provider_error_from_exception",
    "normalize_provider_error",
    "NormalizedProviderError",
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


class ProviderError(ServiceError):
    """Base exception for model provider failures."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "request",
        status_code: int | None = None,
        response_text: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            service=service,
            action=action,
            message=message,
            status_code=status_code,
            response_text=None,
            cause=None,
        )


class _ProviderAuthError(ProviderError, ServiceAuthError):
    """Provider-owned authentication failure."""


class _ProviderRateLimitError(ProviderError, ServiceRateLimitError):
    """Provider-owned rate-limit failure."""


class ProviderConfigError(ProviderError):
    """Raised when a provider is missing required configuration."""

    def __init__(self, message: str, *, service: str = "provider") -> None:
        super().__init__(message, service=service, action="configure")


class ProviderAPIError(ProviderError, ServiceAPIError):
    """Raised when a provider API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "api call",
        status_code: int | None = None,
        response_text: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            service=service,
            action=action,
            status_code=status_code,
            response_text=response_text,
            cause=cause,
        )


class ProviderConnectionError(ProviderError, ServiceNetworkError):
    """Raised when the connection to a provider fails."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        action: str = "connect",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            message,
            service=service,
            action=action,
            cause=cause,
        )


def classify_http_error(
    *,
    service: str,
    action: str,
    status_code: int,
    response_text: str | None = None,
) -> ProviderError:
    """Map a provider HTTP status to a redacted provider-owned error."""
    message = f"{service} {action} failed with status {status_code}"
    if status_code in (401, 403):
        return _ProviderAuthError(
            message,
            service=service,
            action=action,
            status_code=status_code,
        )
    if status_code == 429:
        return _ProviderRateLimitError(
            message,
            service=service,
            action=action,
            status_code=status_code,
        )
    return ProviderAPIError(
        message,
        service=service,
        action=action,
        status_code=status_code,
    )


ClassifyHTTPError = classify_http_error


def _extract_status_code(error: Exception) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int):
            return value

    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _extract_response_text(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if isinstance(response, str):
        return response

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    body = getattr(error, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body

    return None


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
    """Convert provider SDK exceptions into typed service errors."""
    status_code = _extract_status_code(error)
    if isinstance(error, ProviderConfigError):
        return ProviderConfigError(
            f"{service} configuration failed",
            service=service,
        )
    if isinstance(error, ServiceAuthError):
        return _ProviderAuthError(
            f"{service} {action} authentication failed",
            service=service,
            action=action,
            status_code=status_code,
            response_text=None,
            cause=None,
        )
    if isinstance(error, ServiceRateLimitError):
        return _ProviderRateLimitError(
            f"{service} {action} rate limited",
            service=service,
            action=action,
            status_code=status_code,
            response_text=None,
            cause=None,
        )
    if isinstance(error, ServiceNetworkError):
        return ProviderConnectionError(
            f"{service} {action} failed due to a network error",
            service=service,
            action=action,
        )
    if status_code is not None:
        return classify_http_error(
            service=service,
            action=action,
            status_code=status_code,
            response_text=None,
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
        response_text=None,
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
    elif status in (401, 403) or isinstance(error, ServiceAuthError):
        error_type, code, retryable = "auth", "PROVIDER_AUTH_ERROR", False
    elif status == 429 or isinstance(error, ServiceRateLimitError):
        error_type, code, retryable = "rate_limit", "PROVIDER_RATE_LIMITED", True
    elif isinstance(error, ServiceNetworkError):
        error_type, code, retryable = "network", "PROVIDER_NETWORK_ERROR", True
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
