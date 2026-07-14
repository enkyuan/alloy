import json
from pathlib import Path

import pytest

import kaji
from kaji.runtime.providers.errors import (
    ProviderAPIError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ServiceError,
    ServiceAPIError,
    ServiceAuthError,
    ServiceNetworkError,
    ServiceRateLimitError,
    classify_http_error,
    normalize_provider_error,
    provider_error_from_exception,
    service_error_to_detail,
    service_error_to_http_status,
)


PROVIDER_NORMALIZATION_CASES = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "kaji"
        / "contracts"
        / "errors"
        / "provider-normalization.json"
    ).read_text()
)["cases"]


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
    assert error.response_text is None


def test_service_error_to_http_status_mapping():
    assert (
        service_error_to_http_status(
            ServiceAuthError(service="x", action="y", message="m")
        )
        == 401
    )
    assert (
        service_error_to_http_status(
            ServiceRateLimitError(service="x", action="y", message="m")
        )
        == 429
    )
    assert (
        service_error_to_http_status(
            ServiceNetworkError(service="x", action="y", message="m")
        )
        == 503
    )
    assert (
        service_error_to_http_status(
            ServiceAPIError(service="x", action="y", message="m")
        )
        == 502
    )


def test_service_error_to_detail_masks_internals():
    detail = service_error_to_detail(
        ServiceAuthError(service="spotify", action="auth", message="x"),
        fallback="failed",
    )
    assert "authentication failed" in detail


def test_provider_errors_accept_message_only_constructors():
    assert isinstance(ProviderConfigError("missing key"), ProviderConfigError)
    assert isinstance(ProviderAPIError("bad response"), ProviderAPIError)


@pytest.mark.parametrize("status", [401, 403, 429, 400, 500])
def test_public_provider_error_catches_http_classifications(status: int) -> None:
    assert kaji.ProviderError is ProviderError
    error = classify_http_error(
        service="fixture",
        action="request",
        status_code=status,
    )

    with pytest.raises(ProviderError) as captured:
        raise error

    assert captured.value is error


def test_provider_specific_errors_extend_the_service_error_categories() -> None:
    assert issubclass(ProviderAPIError, ServiceAPIError)
    assert issubclass(ProviderConnectionError, ServiceNetworkError)


def test_non_provider_service_errors_stay_outside_the_provider_boundary() -> None:
    error = ServiceAPIError(service="supabase", action="query", message="failed")

    assert not isinstance(error, ProviderError)


@pytest.mark.parametrize(
    "case",
    PROVIDER_NORMALIZATION_CASES,
    ids=[case["name"] for case in PROVIDER_NORMALIZATION_CASES],
)
def test_shared_provider_error_normalization(case: dict[str, object]) -> None:
    source = case["source"]
    status = case["status"]
    if source == "config":
        error: ProviderError = ProviderConfigError("private", service="fixture")
    elif source == "network":
        error = ProviderConnectionError(
            "private",
            service="fixture",
            action="stream",
        )
    else:
        error = ProviderAPIError(
            "private",
            service="fixture",
            action="request",
            status_code=status if isinstance(status, int) else None,
            response_text="private response",
            cause=RuntimeError("private cause"),
        )

    assert isinstance(error, ProviderError)
    assert normalize_provider_error(error) == case["expected"]


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
    error = classify_http_error(
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
    assert isinstance(normalized, ProviderError)
    assert isinstance(normalized, expected_type)
    assert normalized.service == "openai"
    assert normalized.action == ("configure" if kind == "config" else "request")
    assert normalized.response_text is None
    assert normalized.cause is None
    assert normalized.__cause__ is None
    assert normalized.__context__ is None
    assert secret not in str(normalized)
