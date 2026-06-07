import pytest
from pydantic import BaseModel
from unittest.mock import AsyncMock

from agentkit.runtime.tools.registry import (
    ToolContext,
    ToolRegistry,
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


# ---------------------------------------------------------------------------
# list_tool_specs filtering
# ---------------------------------------------------------------------------


def _make_spec(name: str, *, tags: tuple = (), enabled: bool = True) -> ToolSpec:
    return ToolSpec(name=name, description=name, parameters={}, tags=tags, enabled=enabled)


def test_list_tool_specs_excludes_disabled_by_default():
    spec_on = _make_spec("on")
    spec_off = _make_spec("off", enabled=False)
    _TOOL_SPECS["on"] = spec_on
    _TOOL_SPECS["off"] = spec_off
    result = list_tool_specs()
    assert [s.name for s in result] == ["on"]


def test_list_tool_specs_enabled_only_false_returns_all():
    _TOOL_SPECS["on"] = _make_spec("on")
    _TOOL_SPECS["off"] = _make_spec("off", enabled=False)
    result = list_tool_specs(enabled_only=False)
    assert {s.name for s in result} == {"on", "off"}


def test_list_tool_specs_tag_filter_returns_matching():
    _TOOL_SPECS["a"] = _make_spec("a", tags=("payments",))
    _TOOL_SPECS["b"] = _make_spec("b", tags=("crm",))
    _TOOL_SPECS["c"] = _make_spec("c", tags=("payments", "crm"))
    result = list_tool_specs(tags=["payments"])
    assert {s.name for s in result} == {"a", "c"}


def test_list_tool_specs_tag_and_enabled_compose():
    _TOOL_SPECS["a"] = _make_spec("a", tags=("payments",), enabled=False)
    _TOOL_SPECS["b"] = _make_spec("b", tags=("payments",))
    result = list_tool_specs(tags=["payments"])
    assert [s.name for s in result] == ["b"]


def test_list_tool_specs_empty_tags_treated_as_no_filter():
    _TOOL_SPECS["a"] = _make_spec("a", tags=("payments",))
    # empty list = falsy, same as not passing tags — no tag constraint applied
    result = list_tool_specs(tags=[])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_registry_register_and_execute():
    registry = ToolRegistry()
    spec = ToolSpec(name="ping", description="ping", parameters={})

    @registry.register(spec)
    async def ping(_ctx: ToolContext, _args: dict) -> dict:
        return {"pong": True}

    result = await registry.execute("user-1", "ping", {})
    assert result == {"pong": True}


def test_tool_registry_duplicate_raises():
    registry = ToolRegistry()
    spec = ToolSpec(name="dup", description="d", parameters={})

    @registry.register(spec)
    async def first(_ctx, _args):
        return {}

    with pytest.raises(ValueError, match="already registered"):

        @registry.register(spec)
        async def second(_ctx, _args):
            return {}


@pytest.mark.asyncio
async def test_tool_registry_execute_unknown_raises():
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="Unknown tool"):
        await registry.execute("user-1", "ghost", {})


def test_tool_registry_list_specs_filtering():
    registry = ToolRegistry()
    registry._specs["a"] = _make_spec("a", tags=("payments",))
    registry._specs["b"] = _make_spec("b", enabled=False)
    registry._specs["c"] = _make_spec("c", tags=("payments",), enabled=False)

    assert {s.name for s in registry.list_specs()} == {"a"}
    assert {s.name for s in registry.list_specs(enabled_only=False)} == {"a", "b", "c"}
    assert {s.name for s in registry.list_specs(tags=["payments"])} == {"a"}
    assert registry.list_specs(tags=["payments"], enabled_only=False) == [
        registry._specs["a"],
        registry._specs["c"],
    ]


def test_tool_registry_isolation():
    r1 = ToolRegistry()
    r2 = ToolRegistry()
    r1._specs["x"] = _make_spec("x")
    assert r2.list_specs() == []
