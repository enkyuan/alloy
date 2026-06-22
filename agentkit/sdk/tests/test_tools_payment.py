"""Tests for the agentpay bridge tool."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentkit.runtime.tools.payment import RequestPaymentTool


@pytest.mark.asyncio
async def test_request_payment_builds_spec() -> None:
    spec, _handler = RequestPaymentTool(base_url="https://api.example.com")
    assert spec.name == "request_payment"
    props = spec.parameters["properties"]
    assert props["amount"]["type"] == "integer"
    assert props["description"]["type"] == "string"
    assert spec.parameters["required"] == ["amount", "description"]


@pytest.mark.asyncio
async def test_request_payment_posts_to_sessions_endpoint() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.content.decode())))
        return httpx.Response(200, json={"checkoutUrl": "https://pay/abc"})

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(
            base_url="https://api.example.com", client=client
        )
        result = await handler(None, {"amount": 1500, "description": "Coffee"})
        assert result == {"checkoutUrl": "https://pay/abc"}
        assert calls == [
            (
                "https://api.example.com/v1/sessions",
                {"amount": 1500, "description": "Coffee"},
            ),
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_payment_sends_authorization_header() -> None:
    captured: dict[str, str] = {}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(
            base_url="https://x", api_key="sk-test", client=client
        )
        await handler(None, {"amount": 1, "description": "x"})
        assert captured["authorization"] == "Bearer sk-test"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_request_payment_raises_on_non_2xx() -> None:
    def transport_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    transport = httpx.MockTransport(transport_handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        _spec, handler = RequestPaymentTool(base_url="https://x", client=client)
        with pytest.raises(RuntimeError, match="502"):
            await handler(None, {"amount": 1, "description": "x"})
    finally:
        await client.aclose()
