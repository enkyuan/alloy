"""Function-level ``@tool`` for one-off tools without an ``Integration`` subclass.

The class-based ``Integration`` path remains the right shape for namespaced,
multi-tool bundles. This module adds a lightweight alternative for the common
case of "I have one async function; expose it as a tool."

    @tool
    async def get_weather(city: str) -> dict:
        return {"city": city, "tempF": 68}

    runtime = AgentBuilder().provider(p).tool(get_weather).build()

The handler's type hints are introspected to build a Pydantic model, which is
then converted to JSON Schema the same way ``@tool(parameters=Model)`` does.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from typing import Any, Callable, Dict, Optional, Type, Union, cast, get_type_hints

from pydantic import BaseModel, Field, create_model

from kaji.runtime.tools.registry import (
    ToolHandler,
    ToolRegistry,
    ToolSpec,
    provider_safe_tool_name,
    tool_spec_from_model,
)

logger = logging.getLogger(__name__)


def _warn_on_sanitize(original: str, sanitized: str) -> None:
    logger.warning(
        "tool name %r sanitized to %r for provider compatibility",
        original,
        sanitized,
    )


class BoundTool:
    """A single tool packaged with its spec and handler, registrable like an
    ``Integration``. Built by the ``@tool`` decorator; consumed by
    ``AgentBuilder.tool(...)``.
    """

    __slots__ = ("spec", "handler", "namespace")

    def __init__(
        self, spec: ToolSpec, handler: ToolHandler, namespace: str = "fn"
    ) -> None:
        self.spec = spec
        self.handler = handler
        self.namespace = namespace

    def register(self, registry: ToolRegistry) -> None:
        catalog_name = f"{self.namespace}.{self.spec.name}"
        prefixed = replace(
            self.spec,
            name=provider_safe_tool_name(catalog_name, on_mutate=_warn_on_sanitize),
            catalog_name=catalog_name,
        )
        registry.register(prefixed)(self.handler)


def _model_from_signature(fn: Callable[..., Any], model_name: str) -> Type[BaseModel]:
    """Build a Pydantic model from the handler's annotated parameters.

    Skips ``self`` (for methods) and ``ctx`` (the legacy ToolContext parameter).
    Raises ``TypeError`` if a parameter has no annotation; we fail loudly rather
    than guess.
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    fields: Dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name in ("self", "ctx"):
            continue
        if name not in hints:
            raise TypeError(
                f"@tool function {fn.__name__!r} parameter {name!r} has no type "
                "annotation; annotate it or pass parameters= explicitly."
            )
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[name] = (hints[name], Field(default))
    return create_model(model_name, **fields)


def _wrap_handler(fn: Callable[..., Any]) -> ToolHandler:
    """Adapt ``fn(arg1, arg2, ...)`` into the ``(ctx, args_dict)`` shape the
    registry expects.

    The wrapper unpacks ``args_dict`` as keyword arguments and normalises the
    return value: non-dict results (primitives, lists, models) are wrapped as
    ``{"result": ...}`` so the tool log carries a JSON-serialisable object.
    """
    sig = inspect.signature(fn)
    param_names = [n for n in sig.parameters if n not in ("self", "ctx")]

    async def adapter(ctx: Any, args: Dict[str, Any]) -> Dict[str, Any]:
        kwargs = {name: args[name] for name in param_names if name in args}
        result = await fn(**kwargs)
        return result if isinstance(result, dict) else {"result": result}

    return adapter  # type: ignore[return-value]


def function_tool(
    _fn: Optional[Callable[..., Any]] = None,
    *,
    description: Optional[str] = None,
    parameters: Optional[Union[Dict[str, Any], Type[BaseModel]]] = None,
    risk: Optional[str] = None,
    tags: tuple[str, ...] = (),
    enabled: bool = True,
    namespace: str = "fn",
) -> Any:
    """Wrap a bare async function as a registrable tool.

    Usage::

        @function_tool
        async def get_weather(city: str) -> dict:
            return {"city": city, "tempF": 68}

        @function_tool(description="Look up weather.", risk="read")
        async def get_weather(city: str) -> dict: ...

    When ``parameters`` is omitted, the schema is derived from the function's
    type hints. Pass ``parameters=Model`` or a JSON Schema dict to override.
    """

    def make(fn: Callable[..., Any]) -> BoundTool:
        params_schema: Dict[str, Any]
        if parameters is None:
            model = _model_from_signature(fn, f"{fn.__name__}__Args")
            params_schema = tool_spec_from_model("_", "_", model).parameters
        elif isinstance(parameters, type) and issubclass(parameters, BaseModel):
            params_schema = tool_spec_from_model("_", "_", parameters).parameters
        else:
            params_schema = cast(Dict[str, Any], parameters)

        spec = ToolSpec(
            name=fn.__name__,
            description=description or fn.__doc__ or fn.__name__,
            parameters=params_schema,
            risk=risk,
            tags=tags,
            enabled=enabled,
        )
        return BoundTool(spec=spec, handler=_wrap_handler(fn), namespace=namespace)

    # Support both bare ``@tool`` and parameterised ``@tool(...)`` forms.
    if _fn is not None:
        return make(_fn)
    return make
