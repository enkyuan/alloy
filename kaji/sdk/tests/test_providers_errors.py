import pytest

from kaji.runtime.providers.errors import (
    ClassifyHTTPError,
    ProviderAPIError,
    ProviderConfigError,
    ProviderError,
    ServiceError,
    ServiceErrorToDetail,
    ServiceErrorToHTTPStatus,
    ServiceAPIError,
    ServiceAuthError,
    ServiceNetworkError,
    ServiceRateLimitError,
    normalize_provider_error,
    provider_error_from_exception,
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
    error = ClassifyHTTPError(
        service="test", action="fetch", status_code=status, response_text="body"
    )
    assert isinstance(error, expected_type)
    assert error.status_code == status
    assert error.response_text == "body"


def test_service_error_to_http_status_mapping():
    assert (
        ServiceErrorToHTTPStatus(ServiceAuthError(service="x", action="y", message="m"))
        == 401
    )
    assert (
        ServiceErrorToHTTPStatus(
            ServiceRateLimitError(service="x", action="y", message="m")
        )
        == 429
    )
    assert (
        ServiceErrorToHTTPStatus(
            ServiceNetworkError(service="x", action="y", message="m")
        )
        == 503
    )
    assert (
        ServiceErrorToHTTPStatus(ServiceAPIError(service="x", action="y", message="m"))
        == 502
    )


def test_service_error_to_detail_masks_internals():
    detail = ServiceErrorToDetail(
        ServiceAuthError(service="spotify", action="auth", message="x"),
        fallback="failed",
    )
    assert "authentication failed" in detail


def test_provider_errors_accept_message_only_constructors():
    assert isinstance(ProviderConfigError("missing key"), ProviderConfigError)
    assert isinstance(ProviderAPIError("bad response"), ProviderAPIError)


def test_provider_transport_error_has_stable_network_semantics() -> None:
    error = provider_error_from_exception(
        service="openai",
        action="stream",
        error=OSError("private transport detail"),
    )

    assert isinstance(error, ServiceNetworkError)
    assert isinstance(error, ProviderError)
    assert normalize_provider_error(error) == {
        "type": "network",
        "code": "PROVIDER_NETWORK_ERROR",
        "service": "openai",
        "action": "stream",
        "status": None,
        "retryable": True,
    }


def test_vendor_connection_error_is_classified_without_importing_vendor_sdk() -> None:
    class APIConnectionError(Exception):
        pass

    error = provider_error_from_exception(
        service="anthropic",
        action="request",
        error=APIConnectionError("private vendor detail"),
    )

    assert isinstance(error, ServiceNetworkError)
    assert normalize_provider_error(error)["code"] == "PROVIDER_NETWORK_ERROR"


def test_provider_http_error_normalization_preserves_status_and_retryability() -> None:
    error = ClassifyHTTPError(
        service="anthropic",
        action="request",
        status_code=429,
        response_text="private response",
    )

    assert normalize_provider_error(error) == {
        "type": "rate_limit",
        "code": "PROVIDER_RATE_LIMITED",
        "service": "anthropic",
        "action": "request",
        "status": 429,
        "retryable": True,
    }


@pytest.mark.parametrize(
    ("kind", "expected_type", "status_code"),
    [
        ("config", ProviderConfigError, None),
        ("auth", ServiceAuthError, 401),
        ("rate-limit", ServiceRateLimitError, 429),
        ("network", ServiceNetworkError, None),
        ("api", ServiceAPIError, 500),
    ],
)
def test_secret_bearing_service_error_is_reclassified_without_retention(
    kind: str,
    expected_type: type[ServiceError],
    status_code: int | None,
) -> None:
    secret = f"sk-service-{kind}-secret"
    if kind == "config":
        original: ServiceError = ProviderConfigError(secret, service="vendor")
    else:
        error_types: dict[str, type[ServiceError]] = {
            "auth": ServiceAuthError,
            "rate-limit": ServiceRateLimitError,
            "network": ServiceNetworkError,
            "api": ServiceAPIError,
        }
        original = error_types[kind](
            service="vendor",
            action="private-action",
            message=secret,
            status_code=status_code,
            response_text=secret,
            cause=RuntimeError(secret),
        )

    captured: ServiceError | None = None
    try:
        try:
            raise RuntimeError(secret)
        except RuntimeError:
            raise original from None
    except ServiceError as error:
        captured = error

    assert captured is original
    normalized = provider_error_from_exception(
        service="openai",
        action="request",
        error=captured,
    )

    assert normalized is not original
    assert isinstance(normalized, expected_type)
    assert normalized.service == "openai"
    assert normalized.action == ("configure" if kind == "config" else "request")
    assert normalized.response_text is None
    assert normalized.cause is None
    assert normalized.__cause__ is None
    assert normalized.__context__ is None
    assert secret not in str(normalized)
