"""A Stripe test-mode refund through Kaji's public package APIs."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import kaji

StripePost = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]
Approve = Callable[[str], Awaitable[bool]]


async def stripe_post(url: str, form: dict[str, str]) -> dict[str, Any]:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        raise RuntimeError("STRIPE_SECRET_KEY must be a Stripe test-mode secret (sk_test_...)")

    request = Request(
        url,
        data=urlencode(form).encode(),
        headers={"Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed Stripe API URL
        return json.loads(response.read())


class StripeRefunds:
    """Existing product refund function; Kaji does not own this domain client."""

    def __init__(self, post: StripePost = stripe_post) -> None:
        self._post = post

    async def refund(
        self,
        *,
        payment_id: str,
        amount: int,
        idempotency_key: str,
        principal_id: str,
    ) -> dict[str, Any]:
        refund = await self._post(
            "https://api.stripe.com/v1/refunds",
            {
                "payment_intent": payment_id,
                "amount": str(amount),
                "metadata[kaji_principal_id]": principal_id,
            },
        )
        if not isinstance(refund.get("id"), str) or refund.get("status") != "succeeded":
            raise RuntimeError("Stripe did not confirm a succeeded test-mode refund")
        return refund


def refund_capability(refunds: StripeRefunds) -> kaji.Capability:
    @kaji.capability(
        name="payments.refund",
        description="Refund a settled Stripe payment intent in test mode.",
        risk="destructive",
        input_schema={
            "type": "object",
            "properties": {
                "payment_id": {"type": "string", "minLength": 1},
                "amount": {"type": "integer", "minimum": 1},
            },
            "required": ["payment_id", "amount"],
            "additionalProperties": False,
        },
    )
    async def refund(input: dict[str, Any], context: kaji.ToolExecutionContext) -> dict[str, Any]:
        refund = await refunds.refund(
            payment_id=input["payment_id"],
            amount=input["amount"],
            idempotency_key=context.idempotency_key,
            principal_id=context.principal_id,
        )
        refund_id = refund["id"]
        return kaji.capability_result(
            refund,
            [
                kaji.artifact(
                    refund_id,
                    "stripe/refund",
                    f"stripe://refunds/{refund_id}",
                    metadata={"payment_id": input["payment_id"], "amount": input["amount"]},
                )
            ],
        )

    return refund


async def run(
    payment_id: str,
    amount: int,
    *,
    approve: Approve,
    refunds: StripeRefunds | None = None,
) -> kaji.TaskSnapshot:
    """Run the agent request, wait for host approval, then return Task history state."""

    if amount < 1:
        raise ValueError("amount must be positive")
    backend = kaji.InMemoryBackend.create()
    tasks = kaji.TaskRuntime(backend)
    task = await tasks.start(
        task_id="stripe-refund-demo",
        session_id="stripe-refund-session",
        principal_id="demo-user",
        input=f"Refund {payment_id} for {amount} cents.",
    )
    capability = refund_capability(refunds or StripeRefunds())
    runtime = (
        kaji.AgentBuilder()
        .provider(
            kaji.get_provider(
                "mock",
                tool_call={
                    "name": capability.spec.name,
                    "args": {"payment_id": payment_id, "amount": amount},
                },
            )
        )
        .capability(capability)
        .policy(kaji.ToolPolicy(require_approval_for={"destructive"}))
        .approval_handler(kaji.EventApprovalHandler())
        .coordinator(backend.coordinator)
        .tool_idempotency_ledger(backend.idempotency_ledger)
        .build(store=backend.store, journal=backend.journal)
    )
    turn = asyncio.create_task(
        runtime.turn(
            f"Refund {payment_id} for {amount} cents.",
            session_id=task.session_id,
            context=kaji.TurnContext(principal_id="demo-user"),
        )
    )
    while not (pending := await task.pending_approvals()):
        await asyncio.sleep(0)
    approval = pending[0]
    if not await approve(
        f"Approve refund of {amount} cents for {payment_id} as demo-user?"
    ):
        raise RuntimeError("refund was not approved")

    await task.decide_approval(approval, approved=True)
    await turn
    await runtime.append_event(kaji.TaskCompleted(task_id=task.task_id, session_id=task.session_id))
    recovered = tasks.get(task.task_id)
    return await recovered.snapshot()


async def confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


async def main() -> None:
    payment_id = os.environ["STRIPE_PAYMENT_INTENT"]
    amount = int(os.environ["REFUND_AMOUNT_CENTS"])
    snapshot = await run(payment_id, amount, approve=confirm)
    print(json.dumps({"task": snapshot.task_id, "state": snapshot.state.value, "artifacts": [item.uri for item in snapshot.artifacts]}))


if __name__ == "__main__":
    asyncio.run(main())
