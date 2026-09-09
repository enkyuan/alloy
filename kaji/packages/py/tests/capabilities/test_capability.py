from __future__ import annotations

from typing import Any

import pytest

import kaji
from kaji.core.determinism import SystemClock
from kaji.events.store import InMemoryEventStore
from kaji.events.types import EventType
from kaji.runtime.agents.approval import ApprovalDecision
from kaji.runtime.agents.cancel import CancellationToken
from kaji.runtime.agents.context import ToolExecutionContext, ToolInvocation, TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.errors import ToolArgumentValidationError, ToolSchemaValidationError
from kaji.runtime.tools.policy import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry
from tests.helpers.approval import StaticApprovalHandler
from kaji.runtime.providers.mock import MockProvider


def context() -> ToolExecutionContext:
    from kaji.runtime.agents.cancel import CancellationToken

    return ToolExecutionContext(
        principal_id="principal",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=CancellationToken(),
        deadline_monotonic=None,
        db=None,
        metadata={},
    )


@pytest.mark.asyncio
async def test_capability_compiles_to_one_toolspec_and_uses_registry_validation() -> None:
    received: list[ToolExecutionContext] = []

    @kaji.capability(
        name="payments.refund",
        description="Refund a payment.",
        input_schema={
            "type": "object",
            "properties": {"paymentId": {"type": "string"}},
            "required": ["paymentId"],
            "additionalProperties": False,
        },
        risk="destructive",
        timeout_ms=100,
        parallel_safe=True,
        metadata={"owner": "payments"},
    )
    async def refund(input: dict[str, Any], received_context: ToolExecutionContext) -> dict:
        received.append(received_context)
        return {"paymentId": input["paymentId"]}

    registry = ToolRegistry()
    refund.register(registry)
    spec = registry.list_specs(enabled_only=False)[0]
    assert spec.name == "payments.refund"
    assert spec.risk == "destructive"
    assert spec.timeout_ms == 100
    assert spec.parallel_safe is True
    assert refund.metadata == {"owner": "payments"}

    with pytest.raises(ToolArgumentValidationError) as invalid:
        await registry.execute(ToolInvocation("payments.refund", {}, context()))
    assert invalid.value.code == "INVALID_TOOL_ARGUMENTS"

    assert await registry.execute(
        ToolInvocation("payments.refund", {"paymentId": "pay-1"}, context())
    ) == {"paymentId": "pay-1"}
    assert len(received) == 1


@pytest.mark.asyncio
async def test_capability_reuses_timeout_and_idempotency_execution_behavior() -> None:
    @kaji.capability(
        name="timed.capability",
        description="Times out.",
        input_schema={"type": "object"},
        risk="read",
        timeout_ms=1,
    )
    async def timed(_input: dict[str, Any], _context: ToolExecutionContext) -> dict:
        import asyncio

        await asyncio.sleep(0.01)
        return {"ok": True}

    timeout_registry = ToolRegistry()
    timed.register(timeout_registry)
    timeout_planner = ToolPlanner(
        timeout_registry.execute,
        specs={spec.name: spec for spec in timeout_registry.list_specs()},
    )
    result = await timeout_planner.execute_batch(
        "timeout-session",
        [{"id": "timeout-call", "name": "timed.capability", "arguments": {}}],
        lambda _event: _async_none(),
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )
    assert result[0]["error_code"] == "TOOL_TIMEOUT"

    calls = 0

    @kaji.capability(
        name="once.capability",
        description="Runs once.",
        input_schema={"type": "object"},
        risk="read",
        parallel_safe=True,
    )
    async def once(_input: dict[str, Any], _context: ToolExecutionContext) -> dict:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    registry = ToolRegistry()
    once.register(registry)
    planner = ToolPlanner(
        registry.execute,
        specs={spec.name: spec for spec in registry.list_specs()},
    )
    call = [{"id": "same-call", "name": "once.capability", "arguments": {}}]
    for turn_id in ("turn-1", "turn-2"):
        await planner.execute_batch(
            "once-session",
            call,
            lambda _event: _async_none(),
            turn_id=turn_id,
            turn_context=TurnContext(principal_id="principal"),
            cancellation_token=CancellationToken(),
        )
    assert calls == 1
    assert registry.list_specs()[0].parallel_safe is True


async def _async_none() -> None:
    return None


def test_capability_unknown_risk_fails_closed() -> None:
    with pytest.raises(ToolSchemaValidationError) as invalid:

        @kaji.capability(
            name="bad.risk",
            description="Bad risk.",
            input_schema={"type": "object"},
            risk="unknown",  # type: ignore[arg-type]
        )
        async def bad(_input: dict[str, Any], _context: ToolExecutionContext) -> dict:
            return {}

    assert invalid.value.code == "INVALID_TOOL_SCHEMA"


@pytest.mark.asyncio
async def test_builder_capability_preserves_context_approval_and_policy_name() -> None:
    observed: list[ToolExecutionContext] = []

    @kaji.capability(
        name="payments.charge",
        description="Charge a payment.",
        input_schema={
            "type": "object",
            "properties": {"amount": {"type": "integer", "minimum": 1}},
            "required": ["amount"],
            "additionalProperties": False,
        },
        risk="destructive",
    )
    async def charge(_input: dict[str, Any], received: ToolExecutionContext) -> dict:
        observed.append(received)
        return {"charged": True}

    store = InMemoryEventStore()
    runtime = (
        kaji.AgentBuilder()
        .provider(
            MockProvider(
                tool_call={"name": "payments.charge", "args": {"amount": 1}}
            )
        )
        .capability(charge)
        .policy(ToolPolicy(require_approval_for={"destructive"}))
        .approval_handler(StaticApprovalHandler(ApprovalDecision(True, "approved")))
        .default_context(
            TurnContext(
                principal_id="principal-1",
                deadline_monotonic=SystemClock().now_monotonic() + 10,
                metadata={"requestSource": "capability-test"},
            )
        )
        .build(store=store)
    )

    await runtime.send("capability-session", "charge")

    assert len(observed) == 1
    received = observed[0]
    assert received.principal_id == "principal-1"
    assert received.session_id == "capability-session"
    assert received.turn_id
    assert received.tool_call_id == "mock-call-1"
    assert received.idempotency_key == "capability-session:mock-call-1"
    assert received.deadline_monotonic is not None
    assert received.cancellation_token is not None
    assert received.metadata == {"requestSource": "capability-test"}
    types = [event.type for event in await store.get_events("capability-session")]
    assert EventType.TOOL_APPROVAL_APPROVED in types
    assert EventType.TOOL_CALL_COMPLETED in types

    calls = 0

    @kaji.capability(
        name="products.read",
        description="Read products.",
        input_schema={"type": "object"},
        risk="read",
    )
    async def read(_input: dict[str, Any], _context: ToolExecutionContext) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": True}

    denied = (
        kaji.AgentBuilder()
        .provider(MockProvider(tool_call={"name": "products.read", "args": {}}))
        .capability(read)
        .policy(ToolPolicy(denied={"products.read"}))
        .default_context(TurnContext(principal_id="principal"))
        .build()
    )
    await denied.send("denied-capability", "read")
    assert calls == 0
