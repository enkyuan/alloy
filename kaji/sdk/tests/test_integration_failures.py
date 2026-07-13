from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from kaji.infra.events.schemas import ToolCallFailed
from kaji.integrations.errors import (
    IntegrationAuthRequiredError,
    IntegrationExecutionError,
    IntegrationTransportError,
)
from kaji.integrations.recovery import recovery_for_reason
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import ToolInvocation, TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.registry import ToolSpec


class HostileTransportError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        reason_code: str,
        recovery_code: str,
        doc_url: str,
    ) -> None:
        super().__init__("hostile transport")
        self.error_code = error_code
        self.reason_code = reason_code
        self.recovery_code = recovery_code
        self.doc_url = doc_url


def _spec() -> ToolSpec:
    return ToolSpec(
        name="integration",
        description="integration",
        parameters={"type": "object"},
        risk="read",
    )


async def _run(error: BaseException) -> tuple[dict[str, Any], ToolCallFailed]:
    async def executor(_invocation: ToolInvocation) -> None:
        raise error

    events: list[Any] = []
    planner = ToolPlanner(executor, specs={"integration": _spec()})

    async def emit(event: Any) -> None:
        events.append(event)

    results = await planner.execute_batch(
        "session",
        [{"id": "call", "name": "integration", "arguments": {}}],
        emit,
        turn_id="turn",
        turn_context=TurnContext(principal_id="principal"),
        cancellation_token=CancellationToken(),
    )
    failed = next(event for event in events if isinstance(event, ToolCallFailed))
    return results[0], failed


@pytest.mark.asyncio
async def test_provider_confirmed_api_rejection_is_failed_and_nonretryable() -> None:
    recovery = recovery_for_reason("api_rejected")

    result, event = await _run(IntegrationExecutionError("api_rejected"))

    expected = {
        "error_code": "INTEGRATION_API_ERROR",
        "retryable": False,
        "outcome": "failed",
        "reason_code": "api_rejected",
        "recovery_code": recovery.recovery_code,
        "doc_url": recovery.doc_url,
    }
    assert result | expected == result
    assert event.model_dump(exclude_none=True) | expected == event.model_dump(
        exclude_none=True
    )


def test_certified_error_constructors_reject_unknown_transport_outcomes() -> None:
    for reason in (
        "github_mutation_unknown",
        "gmail_mutation_unknown",
        "redirect_rejected",
        "response_limit_exceeded",
        "rate_limited",
        "transient_read_failed",
        "untrusted_reason",
    ):
        with pytest.raises(ValueError):
            IntegrationExecutionError(reason)


@pytest.mark.asyncio
async def test_certified_recovery_survives_result_event_and_idempotent_replay() -> None:
    recovery = recovery_for_reason("github_token_missing")
    error = IntegrationAuthRequiredError("github_token_missing")

    result, event = await _run(error)

    expected = {
        "reason_code": "github_token_missing",
        "recovery_code": recovery.recovery_code,
        "doc_url": recovery.doc_url,
    }
    assert result | expected == result
    assert event.model_dump(exclude_none=True) | expected == event.model_dump(
        exclude_none=True
    )


@pytest.mark.asyncio
async def test_unknown_mutation_keeps_only_closed_recovery_tuple() -> None:
    recovery = recovery_for_reason("github_mutation_unknown")

    result, event = await _run(
        IntegrationTransportError("TOOL_EXECUTION_FAILED", "github_mutation_unknown")
    )

    assert result["error"] == "Tool execution failed"
    assert result["outcome"] == "unknown"
    assert result["reason_code"] == "github_mutation_unknown"
    assert result["recovery_code"] == recovery.recovery_code
    assert event.doc_url == recovery.doc_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_code", "reason_code"),
    [
        ("INTEGRATION_REDIRECT_REJECTED", "redirect_rejected"),
        ("INTEGRATION_RESPONSE_LIMIT", "response_limit_exceeded"),
    ],
)
async def test_canonical_transport_code_survives_as_unknown_outcome(
    error_code: str, reason_code: str
) -> None:
    recovery = recovery_for_reason(reason_code)

    result, event = await _run(IntegrationTransportError(error_code, reason_code))

    expected = {
        "error_code": error_code,
        "retryable": False,
        "outcome": "unknown",
        "reason_code": reason_code,
        "recovery_code": recovery.recovery_code,
        "doc_url": recovery.doc_url,
    }
    assert result | expected == result
    assert event.model_dump(exclude_none=True) | expected == event.model_dump(
        exclude_none=True
    )


@pytest.mark.asyncio
async def test_mismatched_transport_code_is_not_trusted() -> None:
    recovery = recovery_for_reason("redirect_rejected")
    error = HostileTransportError(
        error_code="INTEGRATION_RESPONSE_LIMIT",
        reason_code="redirect_rejected",
        recovery_code=recovery.recovery_code,
        doc_url=recovery.doc_url,
    )

    result, event = await _run(error)

    assert result["error_code"] == "TOOL_EXECUTION_FAILED"
    assert result["outcome"] == "unknown"
    assert "reason_code" not in result
    assert event.error_code == "TOOL_EXECUTION_FAILED"
    assert event.reason_code is None


def test_tool_failure_rejects_partial_or_mismatched_recovery() -> None:
    base: dict[str, Any] = {
        "session_id": "session",
        "turn_id": "turn",
        "tool_name": "integration",
        "tool_call_id": "call",
        "error": "Tool execution failed",
    }
    with pytest.raises(ValidationError):
        ToolCallFailed(**base, reason_code="github_token_missing")
    with pytest.raises(ValidationError):
        ToolCallFailed(
            **base,
            reason_code="github_token_missing",
            recovery_code="CONNECT_GMAIL",
            doc_url=recovery_for_reason("github_token_missing").doc_url,
        )
    recovery = recovery_for_reason("redirect_rejected")
    with pytest.raises(ValidationError):
        ToolCallFailed(
            **base,
            error_code="INTEGRATION_RESPONSE_LIMIT",
            reason_code="redirect_rejected",
            recovery_code=recovery.recovery_code,
            doc_url=recovery.doc_url,
        )
