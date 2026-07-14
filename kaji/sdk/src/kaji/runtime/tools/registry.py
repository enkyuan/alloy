"""Tool registry for LLM-callable functions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import re
import warnings
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Type

from pydantic import BaseModel

from kaji.runtime.context import ToolExecutionContext, ToolInvocation
from kaji.runtime.tools.errors import (
    ToolSchemaValidationError,
    UnclassifiedToolRiskError,
)
from kaji.runtime.tools.validation import ToolSchemaValidator
from kaji.runtime.determinism import IdFactory, SYSTEM_ID_FACTORY

ToolHandler = Callable[
    [ToolExecutionContext, Dict[str, Any]], Awaitable[Dict[str, Any]]
]

# Risk classification for policy enforcement and approval routing. Values
# match policies.RISK_LEVELS, ordered from least to most sensitive.
ToolRisk = Literal["read", "write", "external_effect", "destructive", "admin"]
_TOOL_RISKS = frozenset(("read", "write", "external_effect", "destructive", "admin"))


@dataclass(frozen=True)
class ToolSpec:
    """Definition of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: Dict[str, Any]
    catalog_name: Optional[str] = None
    tags: tuple[str, ...] = ()
    enabled: bool = True
    risk: Optional[ToolRisk] = None
    parallel_safe: bool = False
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        if type(self.parallel_safe) is not bool:
            raise TypeError("parallel_safe must be a boolean")
        if self.timeout_ms is not None:
            if isinstance(self.timeout_ms, bool) or not isinstance(
                self.timeout_ms, int
            ):
                raise TypeError("timeout_ms must be a positive integer or None")
            if self.timeout_ms < 1:
                raise ValueError("timeout_ms must be a positive integer or None")
        if self.risk is None:
            if self.enabled:
                raise UnclassifiedToolRiskError(self.name)
            return
        if self.risk not in _TOOL_RISKS:
            raise ToolSchemaValidationError.invalid_risk(self.name)


def _snapshot_tool_spec(spec: ToolSpec) -> ToolSpec:
    """Return a detached spec whose nested schema cannot mutate ``spec``."""
    return replace(
        spec,
        parameters=deepcopy(spec.parameters),
        tags=tuple(spec.tags),
    )


# Deprecated compatibility name for pre-beta handlers. New code must use the
# canonical ToolExecutionContext public type.
ToolContext = ToolExecutionContext


def provider_safe_tool_name(
    name: str,
    *,
    on_mutate: Optional[Callable[[str, str], None]] = None,
) -> str:
    """Return a provider-safe tool name using only letters, digits, ``_`` and ``-``.

    If ``on_mutate`` is given and the name was changed, the callback fires once
    with ``(original, sanitized)``. Without a callback the sanitizer has no
    side effects (no log, no global state); every registered tool runs through
    it, so a default warn-on-mutation would emit one stderr line per sanitized
    name on every startup. Callers (the integration base classes) thread an
    explicit callback in to surface the mutation through their own logger.
    """
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "tool"
    if safe != name and on_mutate is not None:
        on_mutate(name, safe)
    return safe


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


def tool_spec_from_model(
    name: str,
    description: str,
    model: Type[BaseModel],
    *,
    risk: ToolRisk | None = None,
) -> ToolSpec:
    """Create a tool spec from a Pydantic model."""
    parameters = model.model_json_schema(mode="validation")
    return ToolSpec(
        name=name,
        description=description,
        parameters=parameters,
        risk=risk,
    )


class UnknownToolError(ValueError):
    """Raised when a tool is requested by name but not registered."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"Unknown tool: {tool_name}")
        self.tool_name = tool_name


class ToolRegistry:
    """Scoped tool registry for per-agent or per-tenant isolation.

    The module-level ``register_tool``, ``list_tool_specs``, and ``execute_tool``
    functions delegate to a single process-default registry, sufficient for
    simple single-agent setups. Construct your own ``ToolRegistry`` when you
    need multiple isolated registries or want to pass one explicitly to
    ``AgentRuntime``.

    Example::

        registry = ToolRegistry()

        @registry.register(
            ToolSpec(name="ping", description="...", parameters={}, risk="read")
        )
        async def ping(ctx: ToolExecutionContext, args: dict) -> dict:
            return {"pong": True}

        runtime = AgentRuntime(..., tools=registry.list_specs())
    """

    def __init__(self, *, id_factory: IdFactory | None = None) -> None:
        self._specs: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolHandler] = {}
        self._validators: Dict[str, tuple[ToolSpec, ToolSchemaValidator]] = {}
        self._id_factory = id_factory or SYSTEM_ID_FACTORY

    def register(self, spec: ToolSpec) -> Callable[[ToolHandler], ToolHandler]:
        """Decorator to register a tool handler on this registry instance."""

        def wrapper(func: ToolHandler) -> ToolHandler:
            if spec.name in self._specs:
                raise ValueError(f"Tool already registered: {spec.name}")
            registered_spec = _snapshot_tool_spec(spec)
            validator = ToolSchemaValidator({registered_spec.name: registered_spec})
            self._specs[registered_spec.name] = registered_spec
            self._handlers[registered_spec.name] = func
            self._validators[registered_spec.name] = (registered_spec, validator)
            return func

        return wrapper

    def list_specs(
        self,
        tags: Optional[List[str]] = None,
        enabled_only: bool = True,
    ) -> List[ToolSpec]:
        """Return specs from this registry, optionally filtered."""
        specs = _filter_specs(list(self._specs.values()), tags, enabled_only)
        return [_snapshot_tool_spec(spec) for spec in specs]

    async def execute(
        self,
        invocation: ToolInvocation | str,
        tool_name: str | None = None,
        tool_args: Dict[str, Any] | None = None,
        db: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Execute a tool registered on this registry instance."""
        resolved = _coerce_invocation(
            invocation, tool_name, tool_args, db, self._id_factory
        )
        spec = self._specs.get(resolved.name)
        handler = self._handlers.get(resolved.name)
        if spec is None or handler is None:
            raise UnknownToolError(resolved.name)
        cached = self._validators.get(resolved.name)
        if cached is None or cached[0] is not spec:
            cached = (spec, ToolSchemaValidator({resolved.name: spec}))
            self._validators[resolved.name] = cached
        execution_context = resolved.context.validated_snapshot()
        execution_args = deepcopy(dict(resolved.arguments))
        cached[1].validate(resolved.name, execution_args)
        return await handler(execution_context, execution_args)

    def clear(self) -> None:
        """Clear this registry. Primarily for tests."""
        self._specs.clear()
        self._handlers.clear()
        self._validators.clear()


# Process-default registry that the module-level functions delegate to.
_default_registry = ToolRegistry()

_legacy_execute_warned = False


def _coerce_invocation(
    invocation: ToolInvocation | str,
    tool_name: str | None,
    tool_args: Dict[str, Any] | None,
    db: Any | None,
    id_factory: IdFactory,
) -> ToolInvocation:
    if isinstance(invocation, ToolInvocation):
        if tool_name is not None or tool_args is not None or db is not None:
            raise TypeError("ToolInvocation cannot be combined with legacy arguments")
        return invocation
    if not isinstance(invocation, str) or not isinstance(tool_name, str):
        raise TypeError("execute() requires ToolInvocation")
    if tool_args is None:
        raise TypeError("legacy execute() requires tool arguments")
    global _legacy_execute_warned
    if not _legacy_execute_warned:
        warnings.warn(
            "execute(user_id, name, args, db) is deprecated; pass ToolInvocation",
            DeprecationWarning,
            stacklevel=3,
        )
        _legacy_execute_warned = True
    turn_id = id_factory.next("turn")
    call_id = id_factory.next("tool_call")
    from kaji.runtime.agents.cancellation import CancellationToken  # noqa: PLC0415

    context = ToolExecutionContext(
        principal_id=invocation,
        session_id=turn_id,
        turn_id=turn_id,
        request_id=id_factory.next("request"),
        trace_id=id_factory.next("trace"),
        tool_call_id=call_id,
        idempotency_key=f"{turn_id}:{call_id}",
        cancellation_token=CancellationToken(),
        deadline_monotonic=None,
        db=db,
        metadata={},
    )
    return ToolInvocation(name=tool_name, arguments=tool_args, context=context)


def register_tool(spec: ToolSpec):
    """Decorator to register a tool handler on the process-default registry."""
    return _default_registry.register(spec)


def list_tool_specs(
    tags: Optional[List[str]] = None,
    enabled_only: bool = True,
) -> List[ToolSpec]:
    """Return registered tool specs from the process-default registry."""
    return _default_registry.list_specs(tags=tags, enabled_only=enabled_only)


def clear_tools() -> None:
    """Clear the process-default registry. Primarily for tests."""
    _default_registry.clear()


async def execute_tool(
    invocation: ToolInvocation | str,
    tool_name: str | None = None,
    tool_args: Dict[str, Any] | None = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute a registered tool call against the process-default registry."""
    return await _default_registry.execute(invocation, tool_name, tool_args, db=db)
