from typing import List, Tuple

import pytest
from pydantic import BaseModel, Field

from agentkit.runtime.integrations import Integration, Tool
from agentkit.runtime.tools.registry import (
    ToolContext,
    ToolHandler,
    ToolRegistry,
    ToolSpec,
)


# --- helpers ---

_DUMMY_SPEC = ToolSpec(name="bar", description="A test tool", parameters={})


async def _dummy_handler(ctx: ToolContext, args: dict) -> dict:
    return {"ok": True}


class FooIntegration(Integration):
    namespace = "foo"

    def tools(self) -> List[Tuple[ToolSpec, ToolHandler]]:
        return [(_DUMMY_SPEC, _dummy_handler)]


class MultiToolIntegration(Integration):
    namespace = "svc"

    def tools(self) -> List[Tuple[ToolSpec, ToolHandler]]:
        spec_a = ToolSpec(name="alpha", description="alpha", parameters={})
        spec_b = ToolSpec(name="beta", description="beta", parameters={})
        return [(spec_a, _dummy_handler), (spec_b, _dummy_handler)]


# --- existing tests ---


def test_namespace_creates_provider_safe_tool_names():
    registry = ToolRegistry()
    FooIntegration().register(registry)
    specs = registry.list_specs(enabled_only=False)
    assert [s.name for s in specs] == ["foo_bar"]
    assert [s.catalog_name for s in specs] == ["foo.bar"]


def test_multiple_tools_all_prefixed():
    registry = ToolRegistry()
    MultiToolIntegration().register(registry)
    names = sorted(s.name for s in registry.list_specs(enabled_only=False))
    assert names == ["svc_alpha", "svc_beta"]


def test_cannot_instantiate_without_namespace():
    NoNamespace = type("NoNamespace", (Integration,), {})

    with pytest.raises(TypeError):
        NoNamespace()


# --- @tool decorator tests ---


def test_tool_decorator_auto_registers():
    """A class with @tool-decorated methods exposes them via tools()."""

    class ChargeIntegration(Integration):
        namespace = "stripe"

        @Tool(
            description="Retrieve a charge",
            parameters={"charge_id": {"type": "string"}},
            risk="read",
        )
        async def retrieve_charge(self, ctx: ToolContext, args: dict) -> dict:
            return {}

    integration = ChargeIntegration()
    pairs = integration.tools()
    assert len(pairs) == 1
    spec, handler = pairs[0]
    assert spec.name == "retrieve_charge"
    assert spec.description == "Retrieve a charge"
    assert spec.risk == "read"
    # Bound methods are re-created on each attribute access, so compare by
    # underlying function identity rather than object identity.
    assert handler.__func__ is type(integration).retrieve_charge  # type: ignore[union-attr]


def test_tool_decorator_namespace_prefix():
    """After register(), tool names are provider-safe and retain catalog names."""

    class PayIntegration(Integration):
        namespace = "pay"

        @Tool(
            description="Make a payment",
            parameters={},
            risk="financial",
        )
        async def make_payment(self, ctx: ToolContext, args: dict) -> dict:
            return {}

    registry = ToolRegistry()
    PayIntegration().register(registry)
    specs = registry.list_specs(enabled_only=False)
    assert [s.name for s in specs] == ["pay_make_payment"]
    assert [s.catalog_name for s in specs] == ["pay.make_payment"]


def test_tool_decorator_accepts_pydantic_model():
    """@Tool(parameters=<BaseModel>) converts to JSON Schema at registration."""

    class WeatherArgs(BaseModel):
        city: str = Field(description="City name")
        units: str = "fahrenheit"

    class WeatherIntegration(Integration):
        namespace = "weather"

        @Tool(description="Return weather for a city.", parameters=WeatherArgs, risk="read")
        async def get_weather(self, ctx: ToolContext, args: dict) -> dict:
            return {"city": args["city"]}

    specs = WeatherIntegration().tools()
    assert len(specs) == 1
    spec, _ = specs[0]
    assert spec.parameters["type"] == "object"
    assert "city" in spec.parameters["properties"]
    assert spec.parameters["required"] == ["city"]


def test_tool_decorator_rejects_missing_parameters():
    with pytest.raises(TypeError):
        Tool(description="bad")  # type: ignore[call-arg]


def test_manual_tools_override_still_works():
    """A subclass that manually overrides tools() is unaffected by the decorator scan."""

    custom_spec = ToolSpec(name="custom_op", description="Custom", parameters={})

    class ManualIntegration(Integration):
        namespace = "manual"

        def tools(self) -> List[Tuple[ToolSpec, ToolHandler]]:
            return [(custom_spec, _dummy_handler)]

    registry = ToolRegistry()
    ManualIntegration().register(registry)
    names = [s.name for s in registry.list_specs(enabled_only=False)]
    assert names == ["manual_custom_op"]
