import pytest

from sdk.providers.errors import (
    ProviderAPIError,
    ProviderConfigError,
    ServiceAPIError,
    ServiceAuthError,
    ServiceNetworkError,
    ServiceRateLimitError,
    classify_http_error,
    service_error_to_detail,
    service_error_to_http_status,
)


@pytest.mark.parametrize(
    "status,expected_type",
    [
        (401, ServiceAuthError),
        (403, ServiceAuthError),
        (429, ServiceRateLimitError),
        (500, ServiceAPIError),
        (404, ServiceAPIError),
    ],
)
def test_classify_http_error(status: int, expected_type: type):
    error = classify_http_error(
        service="test", action="fetch", status_code=status, response_text="body"
    )
    assert isinstance(error, expected_type)
    assert error.status_code == status
    assert error.response_text == "body"


def test_service_error_to_http_status_mapping():
    assert service_error_to_http_status(ServiceAuthError(
        service="x", action="y", message="m"
    )) == 401
    assert service_error_to_http_status(ServiceRateLimitError(
        service="x", action="y", message="m"
    )) == 429
    assert service_error_to_http_status(ServiceNetworkError(
        service="x", action="y", message="m"
    )) == 503
    assert service_error_to_http_status(ServiceAPIError(
        service="x", action="y", message="m"
    )) == 502


def test_service_error_to_detail_masks_internals():
    detail = service_error_to_detail(
        ServiceAuthError(service="spotify", action="auth", message="x"),
        fallback="failed",
    )
    assert "authentication failed" in detail


def test_provider_errors_accept_message_only_constructors():
    assert isinstance(ProviderConfigError("missing key"), ProviderConfigError)
    assert isinstance(ProviderAPIError("bad response"), ProviderAPIError)
