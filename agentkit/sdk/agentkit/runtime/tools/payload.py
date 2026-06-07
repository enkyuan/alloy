"""Tool payloads: the neutral format and per-provider translations.

The SDK's neutral tool format is a flat list of dicts::

    [{"name": ..., "description": ..., "parameters": {...}}, ...]

This is what the registry, the agent runtime, and every ``ModelProvider``
exchange. Each provider translates the neutral list into its own
function-calling wire format at its own boundary, using the ``to_*`` helpers
below. Keeping the runtime neutral means a tool works across providers without
the caller knowing which one is configured.
"""

from typing import Any, Dict, List, Optional

from agentkit.runtime.tools.registry import ToolSpec, list_tool_specs


def spec_to_neutral(spec: ToolSpec) -> Dict[str, Any]:
    """One tool spec as a neutral payload entry."""
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
    }


def build_tools_payload(
    allowed_names: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Neutral payload for the registered tools.

    Returns a flat ``[{name, description, parameters}]`` list. Pass
    ``allowed_names`` to restrict to a subset (e.g. the output of a retriever).
    """
    return [
        spec_to_neutral(spec)
        for spec in list_tool_specs()
        if allowed_names is None or spec.name in allowed_names
    ]


# Back-compat alias: this used to return the neutral list under a different name.
tools_fingerprint = build_tools_payload


def to_gemini(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate the neutral list to Gemini's ``function_declarations`` form."""
    if not tools:
        return []
    return [{"function_declarations": tools}]


def to_openai(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Translate the neutral list to OpenAI's ``tools`` form.

    OpenAI (and OpenAI-compatible endpoints like OpenRouter/Kimi) expect
    ``[{"type": "function", "function": {name, description, parameters}}]``.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            },
        }
        for tool in tools
    ]
