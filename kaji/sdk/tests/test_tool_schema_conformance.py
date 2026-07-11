"""Shared Draft 2020-12 tool-schema conformance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kaji.infra.events.schemas import KajiEvent, ToolCallFailed, ToolCallStarted
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import TurnContext
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


def _planner(executor: AsyncMock, **kwargs: Any) -> ToolPlanner:
    async def execute(invocation: Any) -> Any:
        return await executor(invocation)

    return ToolPlanner(execute, **kwargs)


def _spec(case: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        name="fixture_tool",
        description=case["name"],
        parameters=case["schema"],
        risk="read",
    )


def _integer_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }


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
    planner = _planner(executor, specs={"fixture_tool": _spec(case)})
    events: list[KajiEvent] = []

    async def emit(event: KajiEvent) -> None:
        events.append(event)

    result = await planner.execute_batch(
        "session-1",
        [
            {
                "id": "call-1",
                "name": "fixture_tool",
                "arguments": case["arguments"],
            }
        ],
        emit,
        turn_id="test-turn",
        turn_context=TurnContext(principal_id="test-principal"),
        cancellation_token=CancellationToken(),
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
        "message": case["expectedMessage"],
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
                risk="read",
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


def test_validator_owns_a_defensive_schema_snapshot() -> None:
    schema = _integer_object_schema()
    validator = ToolSchemaValidator(
        {
            "fixture_tool": ToolSpec(
                name="fixture_tool",
                description="snapshot",
                parameters=schema,
                risk="read",
            )
        }
    )

    schema["properties"]["value"]["type"] = "not-a-json-schema-type"

    validator.validate("fixture_tool", {"value": 1})
    with pytest.raises(ToolArgumentValidationError, match="type validation"):
        validator.validate("fixture_tool", {"value": "invalid"})


@pytest.mark.asyncio
async def test_registry_snapshots_the_source_spec_at_registration() -> None:
    schema = _integer_object_schema()
    spec = ToolSpec(
        name="fixture_tool",
        description="snapshot",
        parameters=schema,
        catalog_name="catalog.fixture",
        tags=("safe",),
        enabled=False,
        risk="write",
    )
    registry = ToolRegistry()
    handler = AsyncMock(return_value={"ok": True})
    registry.register(spec)(handler)

    schema["properties"]["value"]["type"] = "not-a-json-schema-type"

    registered = registry.list_specs(enabled_only=False)[0]
    assert registered.parameters["properties"]["value"]["type"] == "integer"
    assert registered.catalog_name == "catalog.fixture"
    assert registered.tags == ("safe",)
    assert registered.enabled is False
    assert registered.risk == "write"
    assert await registry.execute("user-1", "fixture_tool", {"value": 1}) == {
        "ok": True
    }
    with pytest.raises(ToolArgumentValidationError, match="type validation"):
        await registry.execute("user-1", "fixture_tool", {"value": "invalid"})
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_registry_list_specs_returns_copy_safe_schemas() -> None:
    registry = ToolRegistry()
    handler = AsyncMock(return_value={"ok": True})
    registry.register(
        ToolSpec(
            name="fixture_tool",
            description="snapshot",
            parameters=_integer_object_schema(),
            risk="read",
        )
    )(handler)

    listed = registry.list_specs()[0]
    listed.parameters["properties"]["value"]["type"] = "not-a-json-schema-type"

    fresh = registry.list_specs()[0]
    assert fresh.parameters["properties"]["value"]["type"] == "integer"
    assert await registry.execute("user-1", "fixture_tool", {"value": 1}) == {
        "ok": True
    }
    with pytest.raises(ToolArgumentValidationError, match="type validation"):
        await registry.execute("user-1", "fixture_tool", {"value": "invalid"})
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_planner_snapshots_source_specs_at_construction() -> None:
    schema = _integer_object_schema()
    specs = {
        "fixture_tool": ToolSpec(
            name="fixture_tool",
            description="snapshot",
            parameters=schema,
            risk="read",
        )
    }
    executor = AsyncMock(return_value={"should": "not run"})
    planner = _planner(executor, specs=specs)
    events: list[KajiEvent] = []

    async def emit(event: KajiEvent) -> None:
        events.append(event)

    schema["properties"]["value"]["type"] = "not-a-json-schema-type"
    specs.clear()

    result = await planner.execute_batch(
        "session-1",
        [
            {
                "id": "call-1",
                "name": "fixture_tool",
                "arguments": {"value": "invalid"},
            }
        ],
        emit,
        turn_id="test-turn",
        turn_context=TurnContext(principal_id="test-principal"),
        cancellation_token=CancellationToken(),
    )

    executor.assert_not_awaited()
    assert result[0]["error_code"] == "INVALID_TOOL_ARGUMENTS"
    assert result[0]["error_path"] == "/value"
    assert not any(isinstance(event, ToolCallStarted) for event in events)
