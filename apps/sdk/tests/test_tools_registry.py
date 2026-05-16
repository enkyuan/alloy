import pytest
from pydantic import BaseModel
from unittest.mock import AsyncMock

from sdk.tools.registry import (
    ToolContext,
    ToolSpec,
    execute_tool,
    list_tool_specs,
    register_tool,
    tool_spec_from_model,
    _TOOL_HANDLERS,
    _TOOL_SPECS,
)


class SampleArgs(BaseModel):
    q: str


@pytest.fixture(autouse=True)
def isolated_registry():
    saved_specs = dict(_TOOL_SPECS)
    saved_handlers = dict(_TOOL_HANDLERS)
    _TOOL_SPECS.clear()
    _TOOL_HANDLERS.clear()
    yield
    _TOOL_SPECS.clear()
    _TOOL_HANDLERS.clear()
    _TOOL_SPECS.update(saved_specs)
    _TOOL_HANDLERS.update(saved_handlers)


def test_tool_spec_from_model_builds_json_schema():
    spec = tool_spec_from_model("search", "Search things", SampleArgs)
    assert spec.name == "search"
    assert "q" in spec.parameters["properties"]


def test_register_tool_rejects_duplicates():
    spec = ToolSpec(name="dup", description="d", parameters={})

    @register_tool(spec)
    async def first(_ctx: ToolContext, _args: dict):
        return {}

    with pytest.raises(ValueError, match="already registered"):

        @register_tool(spec)
        async def second(_ctx: ToolContext, _args: dict):
            return {}


@pytest.mark.asyncio
async def test_execute_tool_unknown_raises():
    db = AsyncMock()
    with pytest.raises(ValueError, match="Unknown tool"):
        await execute_tool("user", "missing", {}, db)


@pytest.mark.asyncio
async def test_execute_tool_invokes_handler():
    spec = ToolSpec(name="echo", description="echo", parameters={})

    @register_tool(spec)
    async def echo(_ctx: ToolContext, args: dict):
        return {"echo": args.get("x")}

    db = AsyncMock()
    result = await execute_tool("user-1", "echo", {"x": 1}, db)
    assert result == {"echo": 1}
    assert len(list_tool_specs()) == 1
