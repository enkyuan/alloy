import inspect
import importlib.util
import json
from pathlib import Path

import pytest

import kaji
from kaji.runtime.providers.errors import (
    ProviderAPIError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitedError,
    classify_http_error,
    normalize_provider_error,
    provider_error_from_exception,
)


PROVIDER_NORMALIZATION_CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "kaji"
        / "contracts"
        / "errors"
        / "provider-normalization.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize(
    "status,expected_type",
    [
        (401, ProviderAPIError),
        (403, ProviderAPIError),
        (429, ProviderRateLimitedError),
        (500, ProviderAPIError),
        (404, ProviderAPIError),
    ],
)
def test_classify_http_error(
    status: int,
    expected_type: type[ProviderError],
) -> None:
    error = classify_http_error(
        service="test",
        action="fetch",
        status_code=status,
    )

    assert isinstance(error, expected_type)
    assert error.status_code == status
    assert not hasattr(error, "response_text")
    assert not hasattr(error, "cause")


def test_provider_error_surface_has_no_discarded_body_or_cause_inputs() -> None:
    parameters = inspect.signature(ProviderAPIError).parameters

    assert "response_text" not in parameters
    assert "cause" not in parameters


def test_provider_errors_accept_message_only_constructors() -> None:
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


def test_provider_error_hierarchy_is_standalone() -> None:
    assert importlib.util.find_spec("kaji.core.errors") is None
    assert ProviderError.__bases__ == (Exception,)
    assert issubclass(ProviderAPIError, ProviderError)
    assert issubclass(ProviderConnectionError, ProviderError)
    assert issubclass(ProviderRateLimitedError, ProviderError)


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
        )

    assert normalize_provider_error(error) == case["expected"]


def test_provider_transport_error_has_stable_network_semantics() -> None:
    error = provider_error_from_exception(
        service="openai",
        action="stream",
        error=OSError("private transport detail"),
    )

    assert isinstance(error, ProviderConnectionError)
    assert normalize_provider_error(error) == {
        "type": "network",
        "code": "PROVIDER_NETWORK_ERROR",
        "service": "openai",
        "action": "stream",
        "status": None,
        "retryable": True,
    }


def test_vendor_connection_error_is_classified_without_vendor_import() -> None:
    class APIConnectionError(Exception):
        pass

    error = provider_error_from_exception(
        service="anthropic",
        action="request",
        error=APIConnectionError("private vendor detail"),
    )

    assert isinstance(error, ProviderConnectionError)
    assert normalize_provider_error(error)["code"] == "PROVIDER_NETWORK_ERROR"


def test_provider_http_error_preserves_rate_limit_semantics() -> None:
    error = classify_http_error(
        service="anthropic",
        action="request",
        status_code=429,
    )

    assert isinstance(error, ProviderRateLimitedError)
    assert normalize_provider_error(error) == {
        "type": "rate_limit",
        "code": "PROVIDER_RATE_LIMITED",
        "service": "anthropic",
        "action": "request",
        "status": 429,
        "retryable": True,
    }


@pytest.mark.parametrize(
    ("original", "expected_type", "expected_action"),
    [
        (
            ProviderConfigError("sk-config-secret", service="vendor"),
            ProviderConfigError,
            "configure",
        ),
        (
            ProviderAPIError(
                "sk-auth-secret",
                service="vendor",
                status_code=401,
            ),
            ProviderAPIError,
            "request",
        ),
        (
            ProviderRateLimitedError("sk-rate-secret", service="vendor"),
            ProviderRateLimitedError,
            "request",
        ),
        (
            ProviderConnectionError("sk-network-secret", service="vendor"),
            ProviderConnectionError,
            "request",
        ),
        (
            ProviderAPIError(
                "sk-api-secret",
                service="vendor",
                status_code=500,
            ),
            ProviderAPIError,
            "request",
        ),
    ],
)
def test_provider_error_is_reclassified_without_private_retention(
    original: ProviderError,
    expected_type: type[ProviderError],
    expected_action: str,
) -> None:
    normalized = provider_error_from_exception(
        service="openai",
        action="request",
        error=original,
    )

    assert normalized is not original
    assert isinstance(normalized, expected_type)
    assert normalized.service == "openai"
    assert normalized.action == expected_action
    assert not hasattr(normalized, "response_text")
    assert not hasattr(normalized, "cause")
    assert normalized.__cause__ is None
    assert normalized.__context__ is None
    assert "sk-" not in str(normalized)


def test_vendor_response_payload_is_not_retained() -> None:
    class VendorError(Exception):
        status_code = 500

        def __init__(self) -> None:
            super().__init__("sk-vendor-message")
            self.response = {"token": "sk-response-secret"}

    error = provider_error_from_exception(
        service="openai",
        action="request",
        error=VendorError(),
    )

    assert isinstance(error, ProviderAPIError)
    assert vars(error) == {
        "service": "openai",
        "action": "request",
        "status_code": 500,
    }
    assert "sk-" not in str(error)
