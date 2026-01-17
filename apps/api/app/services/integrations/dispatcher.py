"""Generic integration tool dispatcher for Hermes."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Type

from pydantic import BaseModel

from sqlalchemy.orm import Session

from app.models.integration import Integration

ToolHandler = Callable[["ToolContext", Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """Definition of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class ToolContext:
    """Execution context for integration tools."""

    user_id: str
    integration: Integration
    db: Session


_TOOL_SPECS: Dict[str, ToolSpec] = {}
_TOOL_HANDLERS: Dict[str, ToolHandler] = {}


def register_tool(spec: ToolSpec):
    """Decorator to register a tool handler."""

    def wrapper(func: ToolHandler) -> ToolHandler:
        if spec.name in _TOOL_SPECS:
            raise ValueError(f"Tool already registered: {spec.name}")
        _TOOL_SPECS[spec.name] = spec
        _TOOL_HANDLERS[spec.name] = func
        return func

    return wrapper


def list_tool_specs() -> List[ToolSpec]:
    """Return all registered tool specs."""

    return list(_TOOL_SPECS.values())


def tool_spec_from_model(
    name: str, description: str, model: Type[BaseModel]
) -> ToolSpec:
    """Create a tool spec from a Pydantic model."""

    schema = model.model_json_schema()
    parameters = {
        "type": "object",
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
        "additionalProperties": False,
    }
    return ToolSpec(name=name, description=description, parameters=parameters)


async def execute_tool(
    user_id: str, tool_name: str, tool_args: Dict[str, Any], db: Session
) -> Dict[str, Any]:
    """Execute a tool call for a given user."""

    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    service_name = tool_name.split(".", 1)[0]
    integration = (
        db.query(Integration)
        .filter(
            Integration.user_id == user_id,
            Integration.service == service_name,
            Integration.is_active == True,
        )
        .first()
    )
    if not integration:
        raise ValueError(f"No active integration for {service_name}")

    ctx = ToolContext(user_id=user_id, integration=integration, db=db)
    return await handler(ctx, tool_args)
