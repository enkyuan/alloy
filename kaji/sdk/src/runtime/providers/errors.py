"""Errors for model providers.

The foundational ``Service*`` errors and HTTP-classification helpers live in
``kaji.core.errors`` (so ``core`` need not depend upward on ``providers``)
and are re-exported here for backwards compatibility. This module adds the
LLM-provider-specific subclasses on top.
"""

from __future__ import annotations

import httpx
from typing import TypedDict

from kaji.core.errors import (
    ServiceAPIError,
    ServiceAuthError,
    ServiceError,
    ServiceNetworkError,
    ServiceRateLimitError,
    classify_http_error,
    service_error_to_detail,
    service_error_to_http_status,
)

ClassifyHTTPError = classify_http_error
ServiceErrorToDetail = service_error_to_detail
ServiceErrorToHTTPStatus = service_error_to_http_status

__all__ = [
    "ClassifyHTTPError",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAPIError",
    "ProviderConnectionError",
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


class NormalizedProviderError(TypedDict):
    """Stable semantic provider failure shape used at SDK boundaries."""

    type: str
    code: str
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
            response_text=response_text,
            cause=cause,
        )


class ProviderConfigError(ProviderError):
    """Raised when a provider is missing required configuration."""

    def __init__(self, message: str, *, service: str = "provider") -> None:
        super().__init__(message, service=service, action="configure")


class ProviderAPIError(ProviderError):
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
            service=service,
            action=action,
            message=message,
            cause=cause,
        )


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
) -> ServiceError:
    """Convert provider SDK exceptions into typed service errors."""
    if isinstance(error, ServiceError):
        return error

    status_code = _extract_status_code(error)
    if status_code is not None:
        return classify_http_error(
            service=service,
            action=action,
            status_code=status_code,
            response_text=_extract_response_text(error),
        )

    if _is_network_error(error):
        return ProviderConnectionError(
            f"{service} {action} failed due to a network error",
            service=service,
            action=action,
            cause=error,
        )

    return ProviderAPIError(
        f"{service} {action} failed: {error}",
        service=service,
        action=action,
        response_text=_extract_response_text(error),
        cause=error,
    )


def normalize_provider_error(error: ServiceError) -> NormalizedProviderError:
    """Return provider-neutral classification without exposing private messages."""
    status = error.status_code
    if isinstance(error, ProviderConfigError):
        error_type, code, retryable = "config", "PROVIDER_CONFIG_ERROR", False
    elif isinstance(error, ServiceAuthError):
        error_type, code, retryable = "auth", "PROVIDER_AUTH_ERROR", False
    elif isinstance(error, ServiceRateLimitError):
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
