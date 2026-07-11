"""Public caller and tool execution context types."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar

from kaji.runtime.determinism import IdFactory, SYSTEM_ID_FACTORY

if TYPE_CHECKING:
    from kaji.runtime.agents.cancellation import CancellationToken


_GENERATED_ID = object()


def _snapshot_arguments(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(value)))


_INVALID_METADATA = "metadata must contain only JSON-like values"


def _deep_freeze_metadata(value: Any, active: set[int]) -> Any:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise TypeError(_INVALID_METADATA)
        return value
    if value_type is dict:
        object_id = id(value)
        if object_id in active:
            raise TypeError(_INVALID_METADATA)
        active.add(object_id)
        try:
            if not all(type(key) is str for key in value):
                raise TypeError(_INVALID_METADATA)
            return MappingProxyType(
                {
                    key: _deep_freeze_metadata(item, active)
                    for key, item in value.items()
                }
            )
        finally:
            active.remove(object_id)
    if value_type in (list, tuple):
        object_id = id(value)
        if object_id in active:
            raise TypeError(_INVALID_METADATA)
        active.add(object_id)
        try:
            return tuple(_deep_freeze_metadata(item, active) for item in value)
        finally:
            active.remove(object_id)
    raise TypeError(_INVALID_METADATA)


def _snapshot_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise TypeError(_INVALID_METADATA)
    return _deep_freeze_metadata(value, set())


def _copy_metadata_snapshot(value: Any) -> Any:
    """Materialize only the immutable container shapes created above."""
    value_type = type(value)
    if value is None or value_type in (bool, int, float, str):
        return value
    if value_type is MappingProxyType:
        return {key: _copy_metadata_snapshot(item) for key, item in value.items()}
    if value_type is tuple:
        return [_copy_metadata_snapshot(item) for item in value]
    raise TypeError(_INVALID_METADATA)


def _normalized_principal(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("principal_id must be a string or None")
    normalized = value.strip()
    if not normalized:
        raise MissingToolIdentityError()
    return normalized


def _required_identifier(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _validated_deadline(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("deadline_monotonic must be a number or None")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < 0:
        raise ValueError("deadline_monotonic must be finite and non-negative")
    return resolved


def _validate_cancellation_token(value: Any) -> None:
    if not all(
        callable(getattr(value, name, None))
        for name in ("cancel", "wait", "raise_if_cancelled")
    ) or not isinstance(getattr(value, "is_cancelled", None), bool):
        raise TypeError(
            "cancellation_token must implement the CancellationToken protocol"
        )


class MissingToolIdentityError(PermissionError):
    """A tool-capable turn was started without a caller principal."""

    code: ClassVar[str] = "MISSING_TOOL_IDENTITY"
    retryable = False
    outcome = "not_started"

    def __init__(self) -> None:
        super().__init__("Tool execution requires a principal identity")


@dataclass(frozen=True, slots=True, init=False)
class TurnContext:
    """Caller-owned context applied to one agent turn."""

    principal_id: str | None
    request_id: str
    trace_id: str
    deadline_monotonic: float | None
    db: Any | None
    metadata: Mapping[str, Any]
    _request_id_generated: bool = field(repr=False, compare=False)
    _trace_id_generated: bool = field(repr=False, compare=False)
    _id_factory: IdFactory = field(repr=False, compare=False)

    def __init__(
        self,
        principal_id: str | None = None,
        request_id: str | object = _GENERATED_ID,
        trace_id: str | object = _GENERATED_ID,
        deadline_monotonic: float | None = None,
        db: Any | None = None,
        metadata: Mapping[str, Any] | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        resolved_factory = id_factory or SYSTEM_ID_FACTORY
        request_generated = request_id is _GENERATED_ID
        trace_generated = trace_id is _GENERATED_ID
        resolved_request = (
            resolved_factory.next("request") if request_generated else request_id
        )
        resolved_trace = resolved_factory.next("trace") if trace_generated else trace_id
        object.__setattr__(self, "principal_id", _normalized_principal(principal_id))
        object.__setattr__(
            self, "request_id", _required_identifier("request_id", resolved_request)
        )
        object.__setattr__(
            self, "trace_id", _required_identifier("trace_id", resolved_trace)
        )
        object.__setattr__(
            self, "deadline_monotonic", _validated_deadline(deadline_monotonic)
        )
        object.__setattr__(self, "db", db)
        object.__setattr__(
            self,
            "metadata",
            _snapshot_metadata({} if metadata is None else metadata),
        )
        object.__setattr__(self, "_request_id_generated", request_generated)
        object.__setattr__(self, "_trace_id_generated", trace_generated)
        object.__setattr__(self, "_id_factory", resolved_factory)

    def refresh_generated_ids(self, id_factory: IdFactory | None = None) -> TurnContext:
        """Clone a builder default, refreshing only auto-generated IDs."""
        return TurnContext(
            principal_id=self.principal_id,
            request_id=(
                _GENERATED_ID if self._request_id_generated else self.request_id
            ),
            trace_id=_GENERATED_ID if self._trace_id_generated else self.trace_id,
            deadline_monotonic=self.deadline_monotonic,
            db=self.db,
            metadata=_copy_metadata_snapshot(self.metadata),
            id_factory=id_factory or self._id_factory,
        )


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Fully resolved authorization and correlation context for one tool call."""

    principal_id: str
    session_id: str
    turn_id: str
    request_id: str
    trace_id: str
    tool_call_id: str
    idempotency_key: str
    cancellation_token: CancellationToken
    deadline_monotonic: float | None
    db: Any | None
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        principal_id = _normalized_principal(self.principal_id)
        if principal_id is None:
            raise MissingToolIdentityError()
        object.__setattr__(self, "principal_id", principal_id)
        for name in (
            "session_id",
            "turn_id",
            "request_id",
            "trace_id",
            "tool_call_id",
        ):
            object.__setattr__(
                self, name, _required_identifier(name, getattr(self, name))
            )
        expected_key = f"{self.session_id}:{self.tool_call_id}"
        if self.idempotency_key != expected_key:
            raise ValueError("idempotency_key must equal '<session_id>:<tool_call_id>'")
        _validate_cancellation_token(self.cancellation_token)
        object.__setattr__(
            self,
            "deadline_monotonic",
            _validated_deadline(self.deadline_monotonic),
        )
        object.__setattr__(self, "metadata", _snapshot_metadata(self.metadata))

    def validated_snapshot(self) -> ToolExecutionContext:
        """Return a detached, revalidated copy for an untrusted registry call."""
        return ToolExecutionContext(
            principal_id=self.principal_id,
            session_id=self.session_id,
            turn_id=self.turn_id,
            request_id=self.request_id,
            trace_id=self.trace_id,
            tool_call_id=self.tool_call_id,
            idempotency_key=self.idempotency_key,
            cancellation_token=self.cancellation_token,
            deadline_monotonic=self.deadline_monotonic,
            db=self.db,
            metadata=_copy_metadata_snapshot(self.metadata),
        )


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """One validated tool dispatch request."""

    name: str
    arguments: Mapping[str, Any]
    context: ToolExecutionContext

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_identifier("name", self.name))
        object.__setattr__(self, "arguments", _snapshot_arguments(self.arguments))
        object.__setattr__(self, "context", self.context.validated_snapshot())
