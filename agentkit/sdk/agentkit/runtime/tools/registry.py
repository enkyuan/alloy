"""Tool registry for LLM-callable functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

ToolHandler = Callable[["ToolContext", Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    """Definition of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]
    tags: tuple[str, ...] = ()
    enabled: bool = True
    # Risk classification for policy enforcement and approval routing.
    # Recognised values: "read", "write", "external_effect", "financial",
    # "destructive", "admin". None means unclassified (treated as "read" by
    # default policies).
    risk: Optional[str] = None


@dataclass(frozen=True)
class ToolContext:
    """Execution context for registered tools.

    ``db`` is optional: tools that don't touch the database (the default for an
    embedded SDK) receive ``None``. Server/worker call paths inject a real
    session when persistence is needed.
    """

    user_id: str
    db: Optional[Any] = None


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


def _filter_specs(
    specs: List[ToolSpec],
    tags: Optional[List[str]],
    enabled_only: bool,
) -> List[ToolSpec]:
    if enabled_only:
        specs = [s for s in specs if s.enabled]
    if tags:
        tag_set = set(tags)
        specs = [s for s in specs if tag_set.intersection(s.tags)]
    return specs


def list_tool_specs(
    tags: Optional[List[str]] = None,
    enabled_only: bool = True,
) -> List[ToolSpec]:
    """Return registered tool specs, optionally filtered by tags or enabled status."""
    return _filter_specs(list(_TOOL_SPECS.values()), tags, enabled_only)


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
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a registered tool call for a given user."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    ctx = ToolContext(user_id=user_id, db=db)
    return await handler(ctx, tool_args)


class ToolRegistry:
    """Scoped tool registry for per-agent or per-tenant isolation.

    The module-level ``register_tool``, ``list_tool_specs``, and ``execute_tool``
    functions share a single global registry suitable for simple single-agent
    setups. Use ``ToolRegistry`` when you need multiple isolated registries or
    want to pass a registry explicitly to ``AgentRuntime``.

    Example::

        registry = ToolRegistry()

        @registry.register(ToolSpec(name="ping", description="...", parameters={}))
        async def ping(ctx: ToolContext, args: dict) -> dict:
            return {"pong": True}

        runtime = AgentRuntime(..., tools=registry.list_specs())
    """

    def __init__(self) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator to register a tool handler on this registry instance."""

        def wrapper(func: ToolHandler) -> ToolHandler:
            if spec.name in self._specs:
                raise ValueError(f"Tool already registered: {spec.name}")
            self._specs[spec.name] = spec
            self._handlers[spec.name] = func
            return func

        return wrapper

    def list_specs(
        self,
        tags: Optional[List[str]] = None,
        enabled_only: bool = True,
    ) -> List[ToolSpec]:
        """Return specs from this registry, optionally filtered."""
        return _filter_specs(list(self._specs.values()), tags, enabled_only)

    async def execute(
        self,
        user_id: str,
        tool_name: str,
        tool_args: Dict[str, Any],
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute a tool registered on this registry instance."""
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        ctx = ToolContext(user_id=user_id, db=db)
        return await handler(ctx, tool_args)
