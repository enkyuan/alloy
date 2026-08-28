"""Reference-service failures and safe API-facing error mappings."""

from __future__ import annotations

from kaji.runtime.providers.errors import (
    ProviderError,
    normalize_provider_error,
)

__all__ = [
    "ServiceAPIError",
    "ServiceAuthError",
    "ServiceError",
    "ServiceNetworkError",
    "ServiceRateLimitError",
    "classify_http_error",
    "provider_error_to_detail",
    "provider_error_to_http_status",
    "service_error_to_detail",
    "service_error_to_http_status",
]


class ServiceError(Exception):
    """Base failure for an external service used by the reference server."""

    def __init__(
        self,
        *,
        service: str,
        action: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.service = service
        self.action = action
        self.status_code = status_code


class ServiceAuthError(ServiceError):
    """Authentication or authorization failure from an external service."""


class ServiceRateLimitError(ServiceError):
    """Rate-limit failure from an external service."""


class ServiceNetworkError(ServiceError):
    """Network-level failure from an external service."""


class ServiceAPIError(ServiceError):
    """Unexpected API-level failure from an external service."""


def classify_http_error(
    *,
    service: str,
    action: str,
    status_code: int,
) -> ServiceError:
    """Map an external-service HTTP status to a payload-free server error."""
    message = f"{service} {action} failed with status {status_code}"
    kwargs = {
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
    """Map a reference-service failure to an API-facing status code."""
    if isinstance(error, ServiceAuthError):
        return 401
    if isinstance(error, ServiceRateLimitError):
        return 429
    if isinstance(error, ServiceNetworkError):
        return 503
    return 502


def service_error_to_detail(error: ServiceError, *, fallback: str) -> str:
    """Map a reference-service failure to a safe client-facing detail."""
    if isinstance(error, ServiceAuthError):
        return f"{error.service} authentication failed"
    if isinstance(error, ServiceRateLimitError):
        return f"{error.service} rate limit reached"
    if isinstance(error, ServiceNetworkError):
        return f"{error.service} is temporarily unavailable"
    return fallback


def provider_error_to_http_status(error: ProviderError) -> int:
    """Map an SDK provider failure to an API-facing status code."""
    error_type = normalize_provider_error(error)["type"]
    if error_type == "auth":
        return 401
    if error_type == "rate_limit":
        return 429
    if error_type == "network":
        return 503
    return 502


def provider_error_to_detail(error: ProviderError, *, fallback: str) -> str:
    """Map an SDK provider failure to a safe client-facing detail."""
    error_type = normalize_provider_error(error)["type"]
    if error_type == "auth":
        return f"{error.service} authentication failed"
    if error_type == "rate_limit":
        return f"{error.service} rate limit reached"
    if error_type == "network":
        return f"{error.service} is temporarily unavailable"
    return fallback
