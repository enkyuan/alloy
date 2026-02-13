"""Typed error classes for external integration service failures."""

from __future__ import annotations

from typing import Any


class IntegrationServiceError(Exception):
    """Base class for integration-related failures."""

    def __init__(
        self,
        *,
        service: str,
        action: str,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.action = action
        self.status_code = status_code
        self.response_text = response_text
        self.cause = cause


class IntegrationAuthError(IntegrationServiceError):
    """Authentication/authorization failure talking to an integration."""


class IntegrationRateLimitError(IntegrationServiceError):
    """Rate-limit failure talking to an integration."""


class IntegrationNetworkError(IntegrationServiceError):
    """Network-level failure talking to an integration."""


class IntegrationAPIError(IntegrationServiceError):
    """Unexpected API-level failure talking to an integration."""


def classify_http_error(
    *,
    service: str,
    action: str,
    status_code: int,
    response_text: str | None = None,
) -> IntegrationServiceError:
    """Map HTTP status codes to a typed integration error."""
    message = f"{service} {action} failed with status {status_code}"
    kwargs: dict[str, Any] = {
        "service": service,
        "action": action,
        "message": message,
        "status_code": status_code,
        "response_text": response_text,
    }
    if status_code in (401, 403):
        return IntegrationAuthError(**kwargs)
    if status_code == 429:
        return IntegrationRateLimitError(**kwargs)
    return IntegrationAPIError(**kwargs)


def integration_error_to_http_status(error: IntegrationServiceError) -> int:
    """Map typed integration errors to API-facing HTTP status codes."""
    if isinstance(error, IntegrationAuthError):
        return 401
    if isinstance(error, IntegrationRateLimitError):
        return 429
    if isinstance(error, IntegrationNetworkError):
        return 503
    return 502


def integration_error_to_detail(
    error: IntegrationServiceError,
    *,
    fallback: str,
) -> str:
    """Convert a typed integration error to a safe client-facing detail."""
    if isinstance(error, IntegrationAuthError):
        return f"{error.service} authentication failed"
    if isinstance(error, IntegrationRateLimitError):
        return f"{error.service} rate limit reached"
    if isinstance(error, IntegrationNetworkError):
        return f"{error.service} is temporarily unavailable"
    return fallback
