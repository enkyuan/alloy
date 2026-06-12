import pytest

from agentkit.runtime.integrations import Integration
from agentkit.runtime.tools.registry import ToolContext, ToolRegistry, ToolSpec


# --- helpers ---

_DUMMY_SPEC = ToolSpec(name="bar", description="A test tool", parameters={})


async def _dummy_handler(ctx: ToolContext, args: dict) -> dict:
    return {"ok": True}


class FooIntegration(Integration):
    namespace = "foo"

    def tools(self):
        return [(_DUMMY_SPEC, _dummy_handler)]


class MultiToolIntegration(Integration):
    namespace = "svc"

    def tools(self):
        spec_a = ToolSpec(name="alpha", description="alpha", parameters={})
        spec_b = ToolSpec(name="beta", description="beta", parameters={})
        return [(spec_a, _dummy_handler), (spec_b, _dummy_handler)]


# --- tests ---


def test_namespace_prefixes_tool_names():
    registry = ToolRegistry()
    FooIntegration().register(registry)
    names = [s.name for s in registry.list_specs(enabled_only=False)]
    assert names == ["foo.bar"]


def test_multiple_tools_all_prefixed():
    registry = ToolRegistry()
    MultiToolIntegration().register(registry)
    names = sorted(s.name for s in registry.list_specs(enabled_only=False))
    assert names == ["svc.alpha", "svc.beta"]


def test_cannot_instantiate_without_namespace():
    class NoNamespace(Integration):
        def tools(self):
            return []

    with pytest.raises(TypeError):
        NoNamespace()


def test_cannot_instantiate_without_tools():
    class NoTools(Integration):
        namespace = "x"

    with pytest.raises(TypeError):
        NoTools()
