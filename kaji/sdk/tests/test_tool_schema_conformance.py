"""Shared Draft 2020-12 tool-schema conformance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kaji.infra.events.schemas import KajiEvent, ToolCallFailed, ToolCallStarted
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.errors import (
    ToolArgumentValidationError,
    ToolSchemaValidationError,
)
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec
from kaji.runtime.tools.validation import ToolSchemaValidator

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_ROOT = REPO_ROOT / "kaji" / "contracts" / "tools"
VALID_CASES = json.loads((CONTRACTS_ROOT / "conformance-valid.json").read_text())[
    "cases"
]
INVALID_CASES = json.loads((CONTRACTS_ROOT / "conformance-invalid.json").read_text())[
    "cases"
]


def _spec(case: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        name="fixture_tool",
        description=case["name"],
        parameters=case["schema"],
    )


@pytest.mark.parametrize("case", VALID_CASES, ids=lambda case: case["name"])
def test_shared_valid_arguments_pass(case: dict[str, Any]) -> None:
    validator = ToolSchemaValidator({"fixture_tool": _spec(case)})
    validator.validate("fixture_tool", case["arguments"])


@pytest.mark.parametrize(
    "case",
    VALID_CASES,
    ids=lambda case: f"registry: {case['name']}",
)
@pytest.mark.asyncio
async def test_shared_valid_arguments_execute_through_direct_registry(
    case: dict[str, Any],
) -> None:
    registry = ToolRegistry()
    handler = AsyncMock(return_value={"ok": True})
    registry.register(_spec(case))(handler)

    result = await registry.execute("user-1", "fixture_tool", case["arguments"])

    assert result == {"ok": True}
    handler.assert_awaited_once()
    awaited = handler.await_args
    assert awaited is not None
    assert awaited.args[1] == case["arguments"]


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["kind"] == "invalid_arguments"],
    ids=lambda case: case["name"],
)
@pytest.mark.asyncio
async def test_shared_invalid_arguments_never_start_or_execute(
    case: dict[str, Any],
) -> None:
    executor = AsyncMock(return_value={"should": "not run"})
    planner = ToolPlanner(executor, specs={"fixture_tool": _spec(case)})
    events: list[KajiEvent] = []

    async def emit(event: KajiEvent) -> None:
        events.append(event)

    result = await planner.execute_scatter_gather(
        "session-1",
        [
            {
                "id": "call-1",
                "name": "fixture_tool",
                "arguments": case["arguments"],
            }
        ],
        emit,
    )

    executor.assert_not_awaited()
    assert len(events) == 2
    assert not any(isinstance(event, ToolCallStarted) for event in events)
    failure = events[-1]
    assert isinstance(failure, ToolCallFailed)
    assert failure.error_code == case["expectedCode"]
    assert failure.error_path == case["expectedPath"]
    assert failure.retryable is case["retryable"]
    assert failure.outcome == case["outcome"]
    assert result[0]["error_code"] == case["expectedCode"]
    assert result[0]["error_path"] == case["expectedPath"]
    assert result[0]["retryable"] is case["retryable"]
    assert result[0]["outcome"] == case["outcome"]


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["kind"] == "invalid_arguments"],
    ids=lambda case: f"registry: {case['name']}",
)
@pytest.mark.asyncio
async def test_direct_registry_execute_rejects_before_handler(
    case: dict[str, Any],
) -> None:
    registry = ToolRegistry()
    handler = AsyncMock(return_value={"should": "not run"})
    registry.register(_spec(case))(handler)

    with pytest.raises(ToolArgumentValidationError) as caught:
        await registry.execute("user-1", "fixture_tool", case["arguments"])

    handler.assert_not_awaited()
    assert caught.value.code == case["expectedCode"]
    assert caught.value.path == case["expectedPath"]
    assert caught.value.retryable is case["retryable"]
    assert caught.value.outcome == case["outcome"]


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["kind"] == "invalid_schema"],
    ids=lambda case: case["name"],
)
def test_shared_invalid_schemas_fail_during_compilation(case: dict[str, Any]) -> None:
    with pytest.raises(ToolSchemaValidationError) as caught:
        ToolSchemaValidator({"fixture_tool": _spec(case)})

    error = caught.value
    assert error.normalized() == {
        "code": case["expectedCode"],
        "path": case["expectedPath"],
        "message": error.message,
    }
    assert error.retryable is case["retryable"]
    assert error.outcome == case["outcome"]


@pytest.mark.parametrize(
    "case",
    [case for case in INVALID_CASES if case["kind"] == "invalid_schema"],
    ids=lambda case: f"registry: {case['name']}",
)
def test_direct_registry_rejects_invalid_schema_atomically(
    case: dict[str, Any],
) -> None:
    registry = ToolRegistry()
    handler = AsyncMock(return_value={"should": "not run"})

    with pytest.raises(ToolSchemaValidationError) as caught:
        registry.register(_spec(case))(handler)

    assert registry.list_specs(enabled_only=False) == []
    handler.assert_not_awaited()
    assert caught.value.code == case["expectedCode"]
    assert caught.value.path == case["expectedPath"]


def test_argument_error_is_bounded_and_does_not_echo_rejected_value() -> None:
    secret = "sk-secret-value-that-must-not-appear"
    validator = ToolSchemaValidator(
        {
            "fixture_tool": ToolSpec(
                name="fixture_tool",
                description="redaction",
                parameters={
                    "type": "object",
                    "properties": {"token": {"type": "string", "pattern": "^allowed$"}},
                },
            )
        }
    )

    with pytest.raises(ToolArgumentValidationError) as caught:
        validator.validate("fixture_tool", {"token": secret})

    assert caught.value.normalized() == {
        "code": "INVALID_TOOL_ARGUMENTS",
        "path": "/token",
        "message": "Tool arguments failed pattern validation at /token",
    }
    assert len(caught.value.message) <= 200
    assert secret not in str(caught.value)
