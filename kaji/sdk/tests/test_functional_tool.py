"""Tests for the function-level ``@function_tool`` path."""

from __future__ import annotations

from typing import Optional

import pytest

from kaji.runtime.agents import (
    AgentBuilder,
    CancellationToken,
    ToolExecutionContext,
)
from kaji.runtime.integrations import BoundTool, function_tool
from kaji.runtime.tools.registry import ToolRegistry
from tests.helpers.mock_provider import MockProvider


@function_tool(risk="read")
async def get_weather(city: str) -> dict:
    """Return weather for a city."""
    return {"city": city, "tempF": 68}


def test_function_tool_produces_bound_tool() -> None:
    assert isinstance(get_weather, BoundTool)
    assert get_weather.spec.name == "get_weather"
    assert get_weather.spec.description == "Return weather for a city."


def test_function_tool_derives_schema_from_type_hints() -> None:
    schema = get_weather.spec.parameters
    assert schema["type"] == "object"
    assert "city" in schema["properties"]
    assert schema["properties"]["city"]["type"] == "string"
    assert schema["required"] == ["city"]
    assert schema["additionalProperties"] is False


def test_function_tool_with_explicit_description() -> None:
    @function_tool(description="Look up search results.", risk="external_effect")
    async def search(query: str, limit: int = 10) -> list:
        return []

    assert search.spec.description == "Look up search results."
    assert search.spec.risk == "external_effect"
    assert search.spec.parameters["required"] == ["query"]
    # `limit` has a default so it shouldn't be required.
    assert "limit" not in search.spec.parameters.get("required", [])


def test_function_tool_rejects_unannotated_parameters() -> None:
    with pytest.raises(TypeError, match="annotat"):

        @function_tool(risk="read")
        async def bad(city) -> dict:  # type: ignore[no-untyped-def]
            return {}


def test_function_tool_registers_with_namespace_prefix() -> None:
    registry = ToolRegistry()
    get_weather.register(registry)
    specs = registry.list_specs(enabled_only=False)
    assert len(specs) == 1
    assert specs[0].name == "fn_get_weather"
    assert specs[0].catalog_name == "fn.get_weather"


@pytest.mark.asyncio
async def test_function_tool_executes_through_agent_builder() -> None:
    @function_tool(risk="read")
    async def echo(message: str) -> dict:
        return {"echoed": message}

    from kaji.runtime.agents.context import TurnContext

    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .tool(echo)
        .default_context(TurnContext(principal_id="test"))
        .build()
    )
    await runtime.send("s1", "hello")
    events = await runtime.history("s1")
    types = [e.type for e in events]

    from kaji.infra.events.types import EventType

    assert EventType.TOOL_CALL_COMPLETED in types


@pytest.mark.asyncio
async def test_function_tool_handler_unpacks_kwargs() -> None:
    """The adapter must forward dict args as keyword arguments to the handler."""

    @function_tool(risk="read")
    async def add(x: int, y: int) -> dict:
        return {"sum": x + y}

    result = await add.handler(None, {"x": 2, "y": 3})
    assert result == {"sum": 5}


@pytest.mark.asyncio
async def test_function_tool_passes_canonical_execution_context() -> None:
    observed: list[ToolExecutionContext] = []

    @function_tool(risk="read")
    async def identify(context: ToolExecutionContext, message: str) -> dict[str, str]:
        observed.append(context)
        return {"message": message, "principal": context.principal_id}

    context = ToolExecutionContext(
        principal_id="tenant",
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
    result = await identify.handler(context, {"message": "hello"})

    assert identify.spec.parameters["properties"].keys() == {"message"}
    assert observed == [context]
    assert result == {"message": "hello", "principal": "tenant"}


@pytest.mark.asyncio
async def test_function_tool_explicitly_adapts_legacy_ctx_parameter() -> None:
    @function_tool(risk="read")
    async def identify(ctx, message: str) -> dict[str, str]:
        return {"message": message, "principal": ctx.principal_id}

    context = ToolExecutionContext(
        principal_id="tenant",
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

    assert await identify.handler(context, {"message": "hello"}) == {
        "message": "hello",
        "principal": "tenant",
    }


def test_function_tool_with_optional_parameter() -> None:
    @function_tool(risk="read")
    async def lookup(name: str, region: Optional[str] = None) -> dict:
        return {"name": name, "region": region}

    schema = lookup.spec.parameters
    assert "name" in schema["required"]
    assert "region" not in schema["required"]
