"""Tests for the function-level ``@function_tool`` path."""

from __future__ import annotations

from typing import Optional

import pytest

from kaji.runtime.agents import AgentBuilder
from kaji.runtime.integrations import BoundTool, function_tool
from kaji.runtime.tools.registry import ToolRegistry
from tests.helpers.mock_provider import MockProvider


@function_tool
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

        @function_tool
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
    @function_tool
    async def echo(message: str) -> dict:
        return {"echoed": message}

    runtime = AgentBuilder().provider(MockProvider()).tool(echo).build()
    await runtime.send("s1", "hello")
    events = await runtime.history("s1")
    types = [e.type for e in events]

    from kaji.infra.events.types import EventType

    assert EventType.TOOL_CALL_COMPLETED in types


@pytest.mark.asyncio
async def test_function_tool_handler_unpacks_kwargs() -> None:
    """The adapter must forward dict args as keyword arguments to the handler."""

    @function_tool
    async def add(x: int, y: int) -> dict:
        return {"sum": x + y}

    result = await add.handler(None, {"x": 2, "y": 3})
    assert result == {"sum": 5}


def test_function_tool_with_optional_parameter() -> None:
    @function_tool
    async def lookup(name: str, region: Optional[str] = None) -> dict:
        return {"name": name, "region": region}

    schema = lookup.spec.parameters
    assert "name" in schema["required"]
    assert "region" not in schema["required"]
