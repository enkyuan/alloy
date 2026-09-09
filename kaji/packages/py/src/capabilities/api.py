"""Product capabilities compiled into the existing tool execution path."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from kaji.capabilities.result import CapabilityResult
from kaji.runtime.agents.context import ToolExecutionContext
from kaji.runtime.tools.registry import ToolHandler, ToolRegistry, ToolRisk, ToolSpec


class Capability:
    """A product operation that registers as one ToolSpec and handler."""

    def __init__(
        self,
        spec: ToolSpec,
        handler: ToolHandler,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.spec = spec
        self.handler = handler
        self.metadata = dict(metadata or {})

    def register(self, registry: ToolRegistry) -> None:
        registry.register(self.spec)(self.handler)


CapabilityFunction = Callable[[dict[str, Any], ToolExecutionContext], Awaitable[Any]]


def capability(
    *,
    name: str,
    description: str,
    input_schema: Mapping[str, Any],
    risk: ToolRisk | None,
    timeout_ms: int | None = None,
    parallel_safe: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> Callable[[CapabilityFunction], Capability]:
    """Decorate an async product operation as a registrable Capability.

    Arguments are validated by ToolRegistry using the supplied JSON Schema;
    the adapter only preserves the existing ``(context, arguments)`` handler
    order and normalizes non-object results like ``function_tool``.
    """

    def decorate(fn: CapabilityFunction) -> Capability:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=dict(input_schema),
            risk=risk,
            parallel_safe=parallel_safe,
            timeout_ms=timeout_ms,
        )

        async def handler(
            context: ToolExecutionContext, arguments: dict[str, Any]
        ) -> dict[str, Any]:
            result = await fn(arguments, context)
            if isinstance(result, CapabilityResult):
                return result
            return result if isinstance(result, dict) else {"result": result}

        return Capability(spec, handler, metadata)

    return decorate
