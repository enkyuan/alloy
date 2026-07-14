import pytest
from pydantic import BaseModel, ConfigDict, Field
from types import SimpleNamespace

from kaji.runtime.agents import CancellationToken, MissingToolIdentityError
from kaji.runtime.context import ToolExecutionContext, ToolInvocation
from kaji.runtime.tools import registry as registry_module
from kaji.runtime.tools.registry import (
    ToolRegistry,
    ToolSpec,
    execute_tool,
    list_tool_specs,
    register_tool,
    tool_spec_from_model,
)


class SampleArgs(BaseModel):
    q: str


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "_default_registry", ToolRegistry())


def test_tool_spec_from_model_builds_json_schema():
    spec = tool_spec_from_model("search", "Search things", SampleArgs, risk="read")
    assert spec.name == "search"
    assert "q" in spec.parameters["properties"]


def test_tool_spec_from_model_preserves_complete_validation_schema():
    class NestedArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

        values: list[int] = Field(min_length=1, max_length=2)

    class ConstrainedArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

        nested: NestedArgs

    expected = ConstrainedArgs.model_json_schema(mode="validation")
    spec = tool_spec_from_model("constrained", "d", ConstrainedArgs, risk="read")

    assert spec.parameters == expected
    assert "$defs" in spec.parameters
    assert spec.parameters["additionalProperties"] is False


def test_register_tool_rejects_duplicates():
    spec = ToolSpec(name="dup", description="d", parameters={}, risk="read")

    @register_tool(spec)
    async def first(_ctx: ToolExecutionContext, _args: dict):
        return {}

    with pytest.raises(ValueError, match="already registered"):

        @register_tool(spec)
        async def second(_ctx: ToolExecutionContext, _args: dict):
            return {}


@pytest.mark.asyncio
async def test_execute_tool_unknown_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await execute_tool(
            ToolInvocation(name="missing", arguments={}, context=_execution_context())
        )


# ---------------------------------------------------------------------------
# list_tool_specs filtering
# ---------------------------------------------------------------------------


def _make_spec(name: str, *, tags: tuple = (), enabled: bool = True) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={},
        tags=tags,
        enabled=enabled,
        risk="read",
    )


def _register_spec(spec: ToolSpec) -> None:
    @register_tool(spec)
    async def handler(
        _context: ToolExecutionContext, _args: dict[str, object]
    ) -> dict[str, bool]:
        return {"ok": True}


def test_list_tool_specs_excludes_disabled_by_default():
    spec_on = _make_spec("on")
    spec_off = _make_spec("off", enabled=False)
    _register_spec(spec_on)
    _register_spec(spec_off)
    result = list_tool_specs()
    assert [s.name for s in result] == ["on"]


def test_list_tool_specs_enabled_only_false_returns_all():
    _register_spec(_make_spec("on"))
    _register_spec(_make_spec("off", enabled=False))
    result = list_tool_specs(enabled_only=False)
    assert {s.name for s in result} == {"on", "off"}


def test_list_tool_specs_tag_filter_returns_matching():
    _register_spec(_make_spec("a", tags=("payments",)))
    _register_spec(_make_spec("b", tags=("crm",)))
    _register_spec(_make_spec("c", tags=("payments", "crm")))
    result = list_tool_specs(tags=["payments"])
    assert {s.name for s in result} == {"a", "c"}


def test_list_tool_specs_tag_and_enabled_compose():
    _register_spec(_make_spec("a", tags=("payments",), enabled=False))
    _register_spec(_make_spec("b", tags=("payments",)))
    result = list_tool_specs(tags=["payments"])
    assert [s.name for s in result] == ["b"]


def test_list_tool_specs_empty_tags_treated_as_no_filter():
    _register_spec(_make_spec("a", tags=("payments",)))
    # empty list = falsy, same as not passing tags — no tag constraint applied
    result = list_tool_specs(tags=[])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_registry_register_and_execute():
    registry = ToolRegistry()
    spec = ToolSpec(name="ping", description="ping", parameters={}, risk="read")

    @registry.register(spec)
    async def ping(_ctx: ToolExecutionContext, _args: dict) -> dict:
        return {"pong": True}

    result = await registry.execute(
        ToolInvocation(name="ping", arguments={}, context=_execution_context())
    )
    assert result == {"pong": True}


def test_tool_registry_duplicate_raises():
    registry = ToolRegistry()
    spec = ToolSpec(name="dup", description="d", parameters={}, risk="read")

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
        await registry.execute(
            ToolInvocation(name="ghost", arguments={}, context=_execution_context())
        )


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


def _execution_context(**overrides) -> ToolExecutionContext:
    values = {
        "principal_id": "tenant",
        "session_id": "session",
        "turn_id": "turn",
        "request_id": "request",
        "trace_id": "trace",
        "tool_call_id": "call",
        "idempotency_key": "session:call",
        "cancellation_token": CancellationToken(),
        "deadline_monotonic": 123.0,
        "db": None,
        "metadata": {"tenant": {"role": "reader"}},
    }
    values.update(overrides)
    return ToolExecutionContext(**values)


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"principal_id": "  "}, MissingToolIdentityError),
        ({"session_id": "  "}, ValueError),
        ({"turn_id": ""}, ValueError),
        ({"request_id": "\t"}, ValueError),
        ({"trace_id": ""}, ValueError),
        ({"tool_call_id": ""}, ValueError),
        ({"idempotency_key": "wrong"}, ValueError),
        ({"deadline_monotonic": float("nan")}, ValueError),
        ({"deadline_monotonic": -1.0}, ValueError),
        ({"cancellation_token": object()}, TypeError),
    ],
)
def test_execution_context_rejects_malformed_invariants(overrides, error) -> None:
    with pytest.raises(error):
        _execution_context(**overrides)


@pytest.mark.asyncio
async def test_registry_revalidates_mutated_canonical_context() -> None:
    registry = ToolRegistry()
    called = False

    @registry.register(_make_spec("safe"))
    async def safe(_context, _args):
        nonlocal called
        called = True
        return {}

    invocation = ToolInvocation(name="safe", arguments={}, context=_execution_context())
    object.__setattr__(invocation.context, "idempotency_key", "tampered")

    with pytest.raises(ValueError, match="idempotency"):
        await registry.execute(invocation)
    assert called is False


def test_execution_context_metadata_is_deeply_immutable() -> None:
    context = _execution_context()
    with pytest.raises(TypeError):
        context.metadata["tenant"]["role"] = "admin"


@pytest.mark.parametrize(
    "value",
    [SimpleNamespace(value=1), bytearray(b"secret"), {"set-value"}, object()],
)
def test_execution_context_rejects_non_json_metadata(value) -> None:
    with pytest.raises(TypeError, match="metadata"):
        _execution_context(metadata={"value": value})


def test_execution_context_preserves_padded_opaque_ids() -> None:
    context = _execution_context(
        session_id=" session ",
        turn_id=" turn ",
        request_id=" request ",
        trace_id=" trace ",
        tool_call_id=" call ",
        idempotency_key=" session : call ",
    )
    assert context.session_id == " session "
    assert context.turn_id == " turn "
    assert context.request_id == " request "
    assert context.trace_id == " trace "
    assert context.tool_call_id == " call "
