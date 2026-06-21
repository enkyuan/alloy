from agentkit.runtime.tools.payload import (
    build_tools_payload,
    spec_to_neutral,
    to_gemini,
    to_openai,
)
from agentkit.runtime.tools.registry import ToolSpec

_NEUTRAL = [
    {
        "name": "lookup",
        "description": "Look something up.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }
]


def test_spec_to_neutral_shape():
    spec = ToolSpec(
        name="catalog_safe_t",
        catalog_name="catalog.safe.t",
        description="d",
        parameters={"type": "object"},
    )
    assert spec_to_neutral(spec) == {
        "name": "catalog_safe_t",
        "description": "d",
        "parameters": {"type": "object"},
    }


def test_build_tools_payload_is_flat_neutral_list(monkeypatch):
    specs = [ToolSpec(name="a", description="A", parameters={"type": "object"})]
    monkeypatch.setattr("agentkit.runtime.tools.payload.list_tool_specs", lambda: specs)
    payload = build_tools_payload()
    # Flat list of {name, description, parameters} — NOT wrapped in
    # function_declarations or {type: function}.
    assert payload == [
        {"name": "a", "description": "A", "parameters": {"type": "object"}}
    ]


def test_build_tools_payload_filters_by_allowed_names(monkeypatch):
    specs = [
        ToolSpec(name="a", description="A", parameters={}),
        ToolSpec(name="b", description="B", parameters={}),
    ]
    monkeypatch.setattr("agentkit.runtime.tools.payload.list_tool_specs", lambda: specs)
    payload = build_tools_payload(allowed_names=["b"])
    assert [t["name"] for t in payload] == ["b"]


def test_to_gemini_wraps_in_function_declarations():
    assert to_gemini(_NEUTRAL) == [{"function_declarations": _NEUTRAL}]


def test_to_gemini_empty_is_empty():
    assert to_gemini([]) == []


def test_to_openai_wraps_each_as_function_tool():
    out = to_openai(_NEUTRAL)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look something up.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
    ]


def test_to_openai_empty_is_empty():
    assert to_openai([]) == []
