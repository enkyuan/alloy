"""Foundational error types for external service calls.

These live in ``core`` (the foundational layer) because ``core.http`` and
``core.auth`` raise them and must not depend upward on ``providers``. The
``providers`` package re-exports these and adds its own LLM-specific
subclasses on top.
"""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """Base class for external service failures."""

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
        # Keep these compatibility attributes, but never retain upstream bodies
        # or exception objects at the public service boundary.
        self.response_text = None
        self.cause = None


class ServiceAuthError(ServiceError):
    """Authentication/authorization failure talking to an external service."""


class ServiceRateLimitError(ServiceError):
    """Rate-limit failure talking to an external service."""


class ServiceNetworkError(ServiceError):
    """Network-level failure talking to an external service."""


class ServiceAPIError(ServiceError):
    """Unexpected API-level failure talking to an external service."""


def classify_http_error(
    *,
    service: str,
    action: str,
    status_code: int,
    response_text: str | None = None,
) -> ServiceError:
    """Map HTTP status codes to a typed, payload-free service error."""
    message = f"{service} {action} failed with status {status_code}"
    kwargs: dict[str, Any] = {
        "service": service,
        "action": action,
        "message": message,
        "status_code": status_code,
    }
    if status_code in (401, 403):
        return ServiceAuthError(**kwargs)
    if status_code == 429:
        return ServiceRateLimitError(**kwargs)
    return ServiceAPIError(**kwargs)


def service_error_to_http_status(error: ServiceError) -> int:
    """Map typed service errors to API-facing HTTP status codes."""
    if isinstance(error, ServiceAuthError):
        return 401
    if isinstance(error, ServiceRateLimitError):
        return 429
    if isinstance(error, ServiceNetworkError):
        return 503
    return 502


def service_error_to_detail(
    error: ServiceError,
    *,
    fallback: str,
) -> str:
    """Convert a typed service error to a safe client-facing detail."""
    if isinstance(error, ServiceAuthError):
        return f"{error.service} authentication failed"
    if isinstance(error, ServiceRateLimitError):
        return f"{error.service} rate limit reached"
    if isinstance(error, ServiceNetworkError):
        return f"{error.service} is temporarily unavailable"
    return fallback
