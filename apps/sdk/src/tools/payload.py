"""Shared helpers for Gemini tool declarations and fingerprints."""

from src.tools.registry import list_tool_specs


def tools_fingerprint() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in list_tool_specs()
    ]


def build_tools_payload(
    allowed_names: list[str] | None = None,
) -> list[dict[str, list[dict[str, object]]]]:
    declarations: list[dict[str, object]] = []
    for spec in list_tool_specs():
        if allowed_names is not None and spec.name not in allowed_names:
            continue
        declarations.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )
    return [{"function_declarations": declarations}] if declarations else []
