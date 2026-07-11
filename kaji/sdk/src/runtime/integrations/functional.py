"""Function-level ``@tool`` for one-off tools without an ``Integration`` subclass.

The class-based ``Integration`` path remains the right shape for namespaced,
multi-tool bundles. This module adds a lightweight alternative for the common
case of "I have one async function; expose it as a tool."

    @function_tool(risk="read")
    async def get_weather(context: ToolExecutionContext, city: str) -> dict:
        return {"city": city, "principal": context.principal_id, "tempF": 68}

    runtime = (
        AgentBuilder()
        .provider(p)
        .tool(get_weather)
        .default_context(TurnContext(principal_id="weather-app"))
        .build()
    )

The handler's type hints are introspected to build a Pydantic model, which is
then converted to JSON Schema the same way ``@tool(parameters=Model)`` does.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from typing import Any, Callable, Dict, Optional, Type, Union, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model

from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools.registry import (
    ToolHandler,
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    provider_safe_tool_name,
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


def _context_parameter(fn: Callable[..., Any]) -> str | None:
    """Find an explicit context parameter without exception-based probing."""
    parameters = [
        parameter
        for parameter in inspect.signature(fn).parameters.values()
        if parameter.name != "self"
    ]
    if not parameters:
        return None
    hints = get_type_hints(fn)
    first = parameters[0]
    if first.name == "ctx" or hints.get(first.name) is ToolExecutionContext:
        return first.name
    if any(
        hints.get(parameter.name) is ToolExecutionContext
        for parameter in parameters[1:]
    ):
        raise TypeError(
            "ToolExecutionContext must be the first function tool parameter"
        )
    return None


def _model_from_signature(
    fn: Callable[..., Any], model_name: str, context_parameter: str | None
) -> Type[BaseModel]:
    """Build a Pydantic model from the handler's annotated parameters.

    Skips ``self`` and the explicitly detected execution-context parameter.
    Raises ``TypeError`` if a tool argument has no annotation; we fail loudly
    rather than guess.
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    fields: Dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "self" or name == context_parameter:
            continue
        if name not in hints:
            fn_name = getattr(fn, "__name__", repr(fn))
            raise TypeError(
                f"@tool function {fn_name!r} parameter {name!r} has no type "
                "annotation; annotate it or pass parameters= explicitly."
            )
        default = param.default if param.default is not inspect.Parameter.empty else ...
        fields[name] = (hints[name], Field(default))
    return create_model(
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _wrap_handler(fn: Callable[..., Any], context_parameter: str | None) -> ToolHandler:
    """Adapt a typed function into the registry's ``(context, args)`` shape.

    The wrapper unpacks ``args_dict`` as keyword arguments and normalises the
    return value: non-dict results (primitives, lists, models) are wrapped as
    ``{"result": ...}`` so the tool log carries a JSON-serialisable object.
    """
    sig = inspect.signature(fn)
    param_names = [
        name for name in sig.parameters if name != "self" and name != context_parameter
    ]

    async def adapter(
        context: ToolExecutionContext, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        kwargs = {name: args[name] for name in param_names if name in args}
        if context_parameter is not None:
            kwargs[context_parameter] = context
        result = await fn(**kwargs)
        return result if isinstance(result, dict) else {"result": result}

    return adapter


def function_tool(
    _fn: Optional[Callable[..., Any]] = None,
    *,
    description: Optional[str] = None,
    parameters: Optional[Union[Dict[str, Any], Type[BaseModel]]] = None,
    risk: Optional[ToolRisk] = None,
    tags: tuple[str, ...] = (),
    enabled: bool = True,
    namespace: str = "fn",
    parallel_safe: bool = False,
    timeout_ms: int | None = None,
) -> Any:
    """Wrap a bare async function as a registrable tool.

    Usage::

        @function_tool(risk="read")
        async def get_weather(city: str) -> dict:
            return {"city": city, "tempF": 68}

        @function_tool(description="Look up weather.", risk="read")
        async def get_weather(city: str) -> dict: ...

    When ``parameters`` is omitted, the schema is derived from the function's
    type hints. Pass ``parameters=Model`` or a JSON Schema dict to override.
    """

    def make(fn: Callable[..., Any]) -> BoundTool:
        fn_name: str = getattr(fn, "__name__", "<anonymous>")
        context_parameter = _context_parameter(fn)
        params_schema: Dict[str, Any]
        if parameters is None:
            model = _model_from_signature(fn, f"{fn_name}__Args", context_parameter)
            params_schema = model.model_json_schema(mode="validation")
        elif isinstance(parameters, type) and issubclass(parameters, BaseModel):
            params_schema = parameters.model_json_schema(mode="validation")
        else:
            params_schema = (
                parameters  # already Dict[str, Any] per the Union guard above
            )

        spec = ToolSpec(
            name=fn_name,
            description=description or getattr(fn, "__doc__", None) or fn_name,
            parameters=params_schema,
            risk=risk,
            tags=tags,
            enabled=enabled,
            parallel_safe=parallel_safe,
            timeout_ms=timeout_ms,
        )
        return BoundTool(
            spec=spec,
            handler=_wrap_handler(fn, context_parameter),
            namespace=namespace,
        )

    # Support both bare ``@tool`` and parameterised ``@tool(...)`` forms.
    if _fn is not None:
        return make(_fn)
    return make
