"""Tool schema helpers used for LLM tool declarations and cache fingerprints."""

from app.services.integrations import list_tool_specs


def tools_fingerprint() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in list_tool_specs()
    ]


def build_tools_payload() -> list[dict[str, list[dict[str, object]]]]:
    declarations: list[dict[str, object]] = []
    for spec in list_tool_specs():
        declarations.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )
    return [{"function_declarations": declarations}] if declarations else []
