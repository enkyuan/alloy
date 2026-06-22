"""`request_payment`: the agentpay bridge tool.

Returns a (ToolSpec, handler) pair. The handler POSTs the args to
``<base_url>/v1/sessions`` and returns the parsed JSON. Pass a custom httpx
client in tests; in production a fresh AsyncClient is created per call.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx

from agentkit.runtime.tools.registry import ToolSpec


PaymentHandler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


def RequestPaymentTool(
    *,
    base_url: str,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[ToolSpec, PaymentHandler]:
    """Build the agentpay bridge tool.

    Parameters
    ----------
    base_url:
        Root URL of the agentpay API (no trailing slash required).
    api_key:
        Optional bearer token. When provided, sent as ``Authorization`` header.
    client:
        Optional pre-built httpx AsyncClient. Useful in tests with MockTransport.
        When omitted, the handler creates a one-shot AsyncClient per call.
    """
    base = base_url.rstrip("/")

    spec = ToolSpec(
        name="request_payment",
        description="Request a payment via agentpay. Returns the checkout URL.",
        parameters={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "Amount in the smallest currency unit (cents).",
                },
                "description": {
                    "type": "string",
                    "description": "Short reason shown to the payer.",
                },
            },
            "required": ["amount", "description"],
        },
        risk="write",
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async def handler(ctx: Any, args: dict[str, Any]) -> Any:
        url = f"{base}/v1/sessions"

        async def _post(c: httpx.AsyncClient) -> Any:
            r = await c.post(url, headers=headers, json=args)
            if r.status_code >= 400:
                raise RuntimeError(
                    f"agentpay POST /v1/sessions failed: {r.status_code} {r.reason_phrase}"
                )
            return r.json()

        if client is not None:
            return await _post(client)
        async with httpx.AsyncClient() as c:
            return await _post(c)

    return spec, handler
