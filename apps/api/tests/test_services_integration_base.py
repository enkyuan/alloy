from __future__ import annotations

import httpx
import pytest

from app.services.integrations.base import IntegrationHTTPService
from app.services.integrations.errors import (
    IntegrationAPIError,
    IntegrationAuthError,
    IntegrationNetworkError,
)


class DummyIntegrationService(IntegrationHTTPService):
    SERVICE_NAME = "dummy"


@pytest.mark.asyncio
async def test_integration_base_request_json_extracts_key() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"collection": [{"id": "1"}]})

    service = DummyIntegrationService()
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        payload = await service._request_json(
            "GET",
            "https://dummy.example/items",
            action="get items",
            response_key="collection",
            default=[],
        )
    finally:
        await service.close()

    assert payload == [{"id": "1"}]


@pytest.mark.asyncio
async def test_integration_base_request_json_raises_typed_auth_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    service = DummyIntegrationService()
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        with pytest.raises(IntegrationAuthError):
            await service._request_json(
                "GET",
                "https://dummy.example/me",
                action="get profile",
            )
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_integration_base_retries_retryable_statuses() -> None:
    request_count = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"ok": True})

    service = DummyIntegrationService()
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        payload = await service._request_json(
            "GET",
            "https://dummy.example/health",
            action="check health",
            retry_attempts=2,
        )
    finally:
        await service.close()

    assert request_count == 2
    assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_integration_base_opens_circuit_after_repeated_failures() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    service = DummyIntegrationService()
    service._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        for _ in range(service.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
            with pytest.raises(IntegrationAPIError):
                await service._request_json(
                    "GET",
                    "https://dummy.example/health",
                    action="check health",
                    retry_attempts=1,
                )

        with pytest.raises(IntegrationNetworkError):
            await service._request_json(
                "GET",
                "https://dummy.example/health",
                action="check health",
                retry_attempts=1,
            )
    finally:
        await service.close()
