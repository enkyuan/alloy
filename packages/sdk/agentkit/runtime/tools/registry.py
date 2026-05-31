"""Tool registry for LLM-callable functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

if TYPE_CHECKING:
    # Imported for typing only — keeps the core tool registry usable without
    # SQLAlchemy installed (it lives behind the optional ``server`` extra).
    from sqlalchemy.ext.asyncio import AsyncSession

ToolHandler = Callable[["ToolContext", Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """Definition of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class ToolContext:
    """Execution context for registered tools.

    ``db`` is optional: tools that don't touch the database (the default for an
    embedded SDK) receive ``None``. Server/worker call paths inject a real
    session when persistence is needed.
    """

    user_id: str
    db: Optional["AsyncSession"] = None


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
    }
    return ToolSpec(name=name, description=description, parameters=parameters)


async def execute_tool(
    user_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    db: Optional["AsyncSession"] = None,
) -> Dict[str, Any]:
    """Execute a registered tool call for a given user."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    ctx = ToolContext(user_id=user_id, db=db)
    return await handler(ctx, tool_args)
