from __future__ import annotations

import asyncio

from refund_agent import StripeRefunds, run


async def main() -> None:
    calls: list[dict[str, str]] = []

    async def post(url: str, form: dict[str, str]) -> dict[str, str]:
        assert url == "https://api.stripe.com/v1/refunds"
        calls.append(form)
        return {"id": "re_test_refund", "status": "succeeded"}

    async def approve(_prompt: str) -> bool:
        return True

    snapshot = await run("pi_test_payment", 500, approve=approve, refunds=StripeRefunds(post))
    assert len(calls) == 1
    assert calls[0]["payment_intent"] == "pi_test_payment"
    assert snapshot.state.value == "completed"
    assert [artifact.uri for artifact in snapshot.artifacts] == ["stripe://refunds/re_test_refund"]


asyncio.run(main())
