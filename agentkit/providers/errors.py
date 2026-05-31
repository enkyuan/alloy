"""Errors for model providers.

The foundational ``Service*`` errors and HTTP-classification helpers live in
``agentkit.core.errors`` (so ``core`` need not depend upward on ``providers``)
and are re-exported here for backwards compatibility. This module adds the
LLM-provider-specific subclasses on top.
"""

from __future__ import annotations

from agentkit.core.errors import (
    ServiceAPIError,
    ServiceAuthError,
    ServiceError,
    ServiceNetworkError,
    ServiceRateLimitError,
    classify_http_error,
    service_error_to_detail,
    service_error_to_http_status,
)

__all__ = [
    "ServiceError",
    "ServiceAuthError",
    "ServiceRateLimitError",
    "ServiceNetworkError",
    "ServiceAPIError",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAPIError",
    "ProviderConnectionError",
    "classify_http_error",
    "service_error_to_http_status",
    "service_error_to_detail",
]


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
        status_code: int | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(
            message,
            service=service,
            action="api call",
            status_code=status_code,
            response_text=response_text,
        )


class ProviderConnectionError(ServiceNetworkError):
    """Raised when the connection to a provider fails."""

    def __init__(
        self,
        message: str,
        *,
        service: str = "provider",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(
            service=service,
            action="connect",
            message=message,
            cause=cause,
        )
