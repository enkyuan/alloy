"""Reference-service error ownership and client-safe mappings."""

from __future__ import annotations

import inspect

import pytest

from kaji.runtime.providers.errors import (
    ProviderAPIError,
    ProviderConnectionError,
    ProviderRateLimitedError,
)
from kaji_serve.server.errors import (
    ServiceAPIError,
    ServiceAuthError,
    ServiceError,
    ServiceNetworkError,
    ServiceRateLimitError,
    classify_http_error,
    provider_error_to_detail,
    provider_error_to_http_status,
    service_error_to_detail,
    service_error_to_http_status,
)


@pytest.mark.parametrize(
    ("status", "expected_type"),
    [
        (401, ServiceAuthError),
        (403, ServiceAuthError),
        (429, ServiceRateLimitError),
        (404, ServiceAPIError),
        (500, ServiceAPIError),
    ],
)
def test_classify_reference_service_http_error(
    status: int,
    expected_type: type[ServiceError],
) -> None:
    error = classify_http_error(
        service="supabase",
        action="request",
        status_code=status,
    )

    assert isinstance(error, expected_type)
    assert error.status_code == status
    assert not hasattr(error, "response_text")
    assert not hasattr(error, "cause")


def test_service_error_surface_has_no_discarded_body_or_cause_inputs() -> None:
    parameters = inspect.signature(ServiceError).parameters

    assert "response_text" not in parameters
    assert "cause" not in parameters


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ServiceAuthError(service="supabase", action="auth", message="private"),
            401,
            "supabase authentication failed",
        ),
        (
            ServiceRateLimitError(
                service="supabase",
                action="query",
                message="private",
            ),
            429,
            "supabase rate limit reached",
        ),
        (
            ServiceNetworkError(
                service="supabase",
                action="query",
                message="private",
            ),
            503,
            "supabase is temporarily unavailable",
        ),
        (
            ServiceAPIError(service="supabase", action="query", message="private"),
            502,
            "request failed",
        ),
    ],
)
def test_reference_service_error_mapping(
    error: ServiceError,
    expected_status: int,
    expected_detail: str,
) -> None:
    assert service_error_to_http_status(error) == expected_status
    assert service_error_to_detail(error, fallback="request failed") == expected_detail


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ProviderAPIError(
                "private",
                service="gemini",
                status_code=401,
            ),
            401,
            "gemini authentication failed",
        ),
        (
            ProviderRateLimitedError("private", service="gemini"),
            429,
            "gemini rate limit reached",
        ),
        (
            ProviderConnectionError("private", service="gemini"),
            503,
            "gemini is temporarily unavailable",
        ),
        (
            ProviderAPIError("private", service="gemini"),
            502,
            "generation failed",
        ),
    ],
)
def test_provider_error_mapping_at_server_boundary(
    error: ProviderAPIError | ProviderConnectionError | ProviderRateLimitedError,
    expected_status: int,
    expected_detail: str,
) -> None:
    assert provider_error_to_http_status(error) == expected_status
    assert (
        provider_error_to_detail(error, fallback="generation failed") == expected_detail
    )
