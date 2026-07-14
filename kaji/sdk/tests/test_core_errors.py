"""Core service failures stay payload-free at public boundaries."""

from __future__ import annotations

import traceback

from kaji.core.errors import ServiceAPIError, classify_http_error


def test_service_error_discards_upstream_body_and_cause() -> None:
    secret = "sk-upstream-service-secret"
    error = ServiceAPIError(
        service="fixture",
        action="request",
        message="fixture request failed",
        response_text=secret,
        cause=RuntimeError(secret),
    )

    assert error.response_text is None
    assert error.cause is None
    assert secret not in str(error)
    assert secret not in "".join(traceback.format_exception(error))


def test_http_classification_discards_upstream_body() -> None:
    secret = "private upstream response"
    error = classify_http_error(
        service="fixture",
        action="request",
        status_code=502,
        response_text=secret,
    )

    assert error.response_text is None
    assert secret not in str(error)
