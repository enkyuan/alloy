from __future__ import annotations

import asyncio
from collections.abc import Mapping
import time
from types import MappingProxyType
from typing import Any

import pytest

import kaji
from kaji.runtime.agents.context import (
    MissingToolIdentityError,
    ToolExecutionContext,
    TurnContext,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.errors import (
    ToolSchemaValidationError,
    UnclassifiedToolRiskError,
)
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec
from kaji.infra.events.types import EventType
from tests.helpers.mock_provider import MockProvider


class CaptureIntegration:
    def __init__(self, seen: list[ToolExecutionContext]) -> None:
        self.seen = seen

    def register(self, registry: ToolRegistry) -> None:
        spec = ToolSpec(
            name="capture",
            description="Capture execution context",
            parameters={"type": "object"},
            risk="read",
        )

        @registry.register(spec)
        async def capture(
            context: ToolExecutionContext, _args: dict[str, Any]
        ) -> dict[str, bool]:
            self.seen.append(context)
            await asyncio.sleep(0)
            return {"captured": True}


@pytest.mark.asyncio
async def test_tool_context_propagates_and_isolates_concurrent_principals() -> None:
    seen: list[ToolExecutionContext] = []
    metadata_a = {"tenant": {"id": "a"}}
    db_a = object()
    token_a = kaji.CancellationToken()
    deadline_a = time.monotonic() + 5
    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(CaptureIntegration(seen))
        .build()
    )

    context_a = TurnContext(
        principal_id="principal-a",
        request_id="request-a",
        trace_id="trace-a",
        deadline_monotonic=deadline_a,
        db=db_a,
        metadata=metadata_a,
    )
    context_b = TurnContext(
        principal_id="principal-b",
        request_id="request-b",
        trace_id="trace-b",
        metadata={"tenant": {"id": "b"}},
    )
    metadata_a["tenant"]["id"] = "mutated"

    result_a, result_b = await asyncio.gather(
        runtime.turn(
            "capture",
            session_id="session-a",
            cancellation_token=token_a,
            context=context_a,
        ),
        runtime.turn("capture", session_id="session-b", context=context_b),
    )

    by_session = {context.session_id: context for context in seen}
    captured_a = by_session["session-a"]
    captured_b = by_session["session-b"]
    assert captured_a.principal_id == "principal-a"
    assert captured_b.principal_id == "principal-b"
    assert captured_a.turn_id == result_a.turn_id
    assert captured_b.turn_id == result_b.turn_id
    assert captured_a.request_id == "request-a"
    assert captured_a.trace_id == "trace-a"
    assert captured_a.tool_call_id == "mock-call-1"
    assert captured_a.idempotency_key == "session-a:mock-call-1"
    assert captured_a.cancellation_token is not token_a
    assert captured_a.deadline_monotonic == deadline_a
    assert captured_a.db is db_a
    assert captured_a.metadata == {"tenant": {"id": "a"}}


@pytest.mark.asyncio
async def test_tool_enabled_turn_requires_identity_before_approval_or_execution() -> (
    None
):
    seen: list[ToolExecutionContext] = []
    approvals = 0

    async def approve(_name: str, _args: dict[str, Any], _risk: str | None) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(CaptureIntegration(seen))
        .policy(ToolPolicy(require_approval_for={"read"}))
        .approval_handler(approve)
        .build()
    )

    with pytest.raises(MissingToolIdentityError) as raised:
        await runtime.turn("capture", session_id="missing-principal")

    assert raised.value.code == "MISSING_TOOL_IDENTITY"
    assert approvals == 0
    assert seen == []
    events = await runtime.history("missing-principal")
    assert EventType.TOOL_CALL_REQUESTED not in [event.type for event in events]

    await runtime.turn(
        "capture with identity",
        session_id="missing-principal",
        context=TurnContext(principal_id="recovered"),
    )
    assert seen[-1].principal_id == "recovered"


@pytest.mark.asyncio
async def test_no_tool_turn_may_omit_context() -> None:
    runtime = kaji.AgentBuilder().provider(MockProvider()).build()
    result = await runtime.turn("hello", session_id="no-tools")
    assert result.text == "mock"


@pytest.mark.asyncio
async def test_builder_default_context_is_explicit_and_refreshes_generated_ids() -> (
    None
):
    seen: list[ToolExecutionContext] = []
    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(CaptureIntegration(seen))
        .default_context(TurnContext(principal_id="single-tenant"))
        .build()
    )

    await runtime.turn("capture", session_id="default-a")
    await runtime.turn("capture", session_id="default-b")

    assert [context.principal_id for context in seen] == [
        "single-tenant",
        "single-tenant",
    ]
    assert seen[0].request_id != seen[1].request_id
    assert seen[0].trace_id != seen[1].trace_id


def test_context_types_are_public() -> None:
    assert kaji.TurnContext is TurnContext
    assert kaji.ToolExecutionContext is ToolExecutionContext
    assert kaji.ToolInvocation.__name__ == "ToolInvocation"


def test_enabled_tools_require_a_known_risk() -> None:
    with pytest.raises(UnclassifiedToolRiskError) as missing:
        ToolSpec(name="missing", description="missing", parameters={})
    assert missing.value.code == "UNCLASSIFIED_TOOL_RISK"

    with pytest.raises(ToolSchemaValidationError) as unknown:
        ToolSpec(
            name="unknown",
            description="unknown",
            parameters={},
            risk="typo",  # ty: ignore[invalid-argument-type]
        )
    assert unknown.value.code == "INVALID_TOOL_SCHEMA"


@pytest.mark.asyncio
async def test_principal_is_trimmed_and_whitespace_fails_before_tool_events() -> None:
    seen: list[ToolExecutionContext] = []
    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(CaptureIntegration(seen))
        .build()
    )

    with pytest.raises(MissingToolIdentityError):
        await runtime.turn(
            "capture",
            session_id="whitespace-principal",
            context=TurnContext(principal_id="  \t "),
        )

    events = await runtime.history("whitespace-principal")
    assert EventType.TOOL_CALL_REQUESTED not in [event.type for event in events]
    assert seen == []

    await runtime.turn(
        "capture",
        session_id="trimmed-principal",
        context=TurnContext(principal_id="  tenant-a  "),
    )
    assert seen[-1].principal_id == "tenant-a"


@pytest.mark.asyncio
async def test_reused_explicit_context_refreshes_only_generated_ids() -> None:
    seen: list[ToolExecutionContext] = []
    runtime = (
        kaji.AgentBuilder()
        .provider(MockProvider())
        .integration(CaptureIntegration(seen))
        .build()
    )
    generated = TurnContext(principal_id="tenant")
    explicit = TurnContext(
        principal_id="tenant",
        request_id="request-fixed",
        trace_id="trace-fixed",
    )

    await runtime.turn("capture", session_id="generated-a", context=generated)
    await runtime.turn("capture", session_id="generated-b", context=generated)
    await runtime.turn("capture", session_id="explicit-a", context=explicit)
    await runtime.turn("capture", session_id="explicit-b", context=explicit)

    by_session = {context.session_id: context for context in seen}
    assert by_session["generated-a"].request_id != by_session["generated-b"].request_id
    assert by_session["generated-a"].trace_id != by_session["generated-b"].trace_id
    assert by_session["explicit-a"].request_id == "request-fixed"
    assert by_session["explicit-b"].request_id == "request-fixed"
    assert by_session["explicit-a"].trace_id == "trace-fixed"
    assert by_session["explicit-b"].trace_id == "trace-fixed"


def test_context_metadata_is_deeply_immutable_and_detached() -> None:
    source = {"tenant": {"roles": ["reader"]}}
    context = TurnContext(principal_id="tenant", metadata=source)
    source["tenant"]["roles"].append("admin")

    assert tuple(context.metadata["tenant"]["roles"]) == ("reader",)
    with pytest.raises(TypeError):
        context.metadata["tenant"]["roles"][0] = "admin"
    with pytest.raises(TypeError):
        context.metadata["tenant"]["new"] = True


def test_context_metadata_rejects_custom_mapping_without_executing_hooks() -> None:
    touched: list[str] = []

    class SideEffectMapping(Mapping[str, Any]):
        def __getitem__(self, key: str) -> Any:
            touched.append(f"getitem:{key}")
            raise AssertionError("custom mapping hook executed")

        def __iter__(self):
            touched.append("iter")
            raise AssertionError("custom mapping hook executed")

        def __len__(self) -> int:
            touched.append("len")
            raise AssertionError("custom mapping hook executed")

    hostile = SideEffectMapping()
    for metadata in (hostile, MappingProxyType(hostile), {"nested": hostile}):
        with pytest.raises(
            TypeError, match="metadata must contain only JSON-like values"
        ):
            TurnContext(principal_id="tenant", metadata=metadata)

    assert touched == []


def test_context_metadata_rejects_cycles_with_stable_error() -> None:
    metadata: dict[str, Any] = {}
    metadata["self"] = metadata

    with pytest.raises(TypeError, match="metadata must contain only JSON-like values"):
        TurnContext(principal_id="tenant", metadata=metadata)


def test_turn_context_rejects_blank_required_ids() -> None:
    with pytest.raises(ValueError, match="request_id"):
        TurnContext(principal_id="tenant", request_id="  ")
    with pytest.raises(ValueError, match="trace_id"):
        TurnContext(principal_id="tenant", trace_id="  ")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "calls,specs",
    [
        ([{"id": "call", "name": "missing", "arguments": {}}], {}),
        (
            [{"id": "call", "name": "disabled", "arguments": {}}],
            {
                "disabled": ToolSpec(
                    name="disabled",
                    description="disabled",
                    parameters={},
                    enabled=False,
                )
            },
        ),
        (
            [{"id": "", "name": "safe", "arguments": {}}],
            {
                "safe": ToolSpec(
                    name="safe", description="safe", parameters={}, risk="read"
                )
            },
        ),
        (
            [
                {"id": "duplicate", "name": "safe", "arguments": {}},
                {"id": "duplicate", "name": "safe", "arguments": {}},
            ],
            {
                "safe": ToolSpec(
                    name="safe", description="safe", parameters={}, risk="read"
                )
            },
        ),
    ],
)
async def test_planner_rejects_invalid_call_contract_before_any_event(
    calls: list[dict[str, Any]], specs: dict[str, ToolSpec]
) -> None:
    events: list[Any] = []
    executed = False

    async def executor(_invocation: Any) -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    async def emit(event: Any) -> None:
        events.append(event)

    planner = ToolPlanner(executor=executor, specs=specs)
    with pytest.raises((UnclassifiedToolRiskError, ValueError)):
        await planner.execute_scatter_gather(
            "session",
            calls,
            emit,
            turn_id="turn",
            turn_context=TurnContext(principal_id="tenant"),
            cancellation_token=CancellationToken(),
        )

    assert events == []
    assert executed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_id,turn_id,cancellation_token",
    [
        ("", "turn", CancellationToken()),
        ("session", "  ", CancellationToken()),
        ("session", "turn", object()),
    ],
)
async def test_planner_rejects_invalid_context_before_any_event(
    session_id: str,
    turn_id: str,
    cancellation_token: Any,
) -> None:
    events: list[Any] = []
    spec = ToolSpec(name="safe", description="safe", parameters={}, risk="read")

    async def executor(_invocation: Any) -> dict[str, bool]:
        return {"ok": True}

    async def emit(event: Any) -> None:
        events.append(event)

    planner = ToolPlanner(executor=executor, specs={"safe": spec})
    with pytest.raises((TypeError, ValueError)):
        await planner.execute_scatter_gather(
            session_id,
            [{"id": "call", "name": "safe", "arguments": {}}],
            emit,
            turn_id=turn_id,
            turn_context=TurnContext(principal_id="tenant"),
            cancellation_token=cancellation_token,
        )
    assert events == []
