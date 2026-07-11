"""Typed approval decisions and the canonical event-backed bridge."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import inspect
import math
from types import MappingProxyType
from typing import Any, Literal, Protocol, TypeAlias, cast, runtime_checkable
import warnings

from kaji.infra.events.protocols import EventJournal, EventSubscription
from kaji.infra.events.schemas import (
    StoredKajiEvent,
    require_stored_event,
)
from kaji.infra.events.types import EventType
from kaji.runtime.context import ToolExecutionContext, ToolInvocation
from kaji.runtime.tools.registry import ToolRisk


ApprovalCode: TypeAlias = Literal[
    "approved", "rejected", "timeout", "cancelled", "unavailable"
]
ApprovalErrorCode: TypeAlias = Literal[
    "APPROVAL_REJECTED",
    "APPROVAL_TIMEOUT",
    "TOOL_CANCELLED",
    "APPROVAL_UNAVAILABLE",
]
ApprovalRequester: TypeAlias = Callable[[], Awaitable[StoredKajiEvent]]
ApprovalObserver: TypeAlias = Callable[[StoredKajiEvent], Awaitable[None]]
LegacyApprovalCallback: TypeAlias = Callable[
    [str, dict[str, Any], str | None], Awaitable[bool]
]

_MAX_REASON_LENGTH = 200
_APPROVAL_CODES = frozenset(
    {"approved", "rejected", "timeout", "cancelled", "unavailable"}
)
_RISKS = frozenset(
    {"read", "write", "external_effect", "financial", "destructive", "admin"}
)
_legacy_handler_warned = False


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Closed approval result shared by local and event-backed handlers."""

    granted: bool
    code: ApprovalCode
    reason: str | None = None
    recorded: bool = False

    def __post_init__(self) -> None:
        if type(self.granted) is not bool or type(self.recorded) is not bool:
            raise TypeError("granted and recorded must be booleans")
        if self.code not in _APPROVAL_CODES:
            raise ValueError("approval code must use the closed approval vocabulary")
        if self.granted:
            if self.code != "approved":
                raise ValueError("a granted decision must use code 'approved'")
            if self.reason is not None:
                raise ValueError("an approved decision cannot include a reason")
            return
        if self.code == "approved":
            raise ValueError("a negative decision cannot use code 'approved'")
        if not isinstance(self.reason, str):
            raise TypeError("a negative decision requires a string reason")
        reason = self.reason.strip()
        if not reason:
            raise ValueError("a negative decision requires a non-empty reason")
        if len(reason) > _MAX_REASON_LENGTH:
            raise ValueError(
                f"approval reason cannot exceed {_MAX_REASON_LENGTH} characters"
            )


@dataclass(frozen=True, slots=True)
class ApprovalRequestContext:
    """Runtime-owned correlation, delivery, cancellation, and deadline state."""

    tool_context: ToolExecutionContext
    risk: ToolRisk
    arguments: Mapping[str, Any]
    journal: EventJournal
    request: ApprovalRequester
    observe: ApprovalObserver
    deadline_monotonic: float

    def __post_init__(self) -> None:
        if self.risk not in _RISKS:
            raise ValueError("approval risk must use the canonical risk vocabulary")
        if not callable(self.request):
            raise TypeError("approval request must be callable")
        if not callable(self.observe):
            raise TypeError("approval observer must be callable")
        if not callable(getattr(self.journal, "open_subscription", None)):
            raise TypeError("approval journal must open ready, closable subscriptions")
        if isinstance(self.deadline_monotonic, bool) or not isinstance(
            self.deadline_monotonic, (int, float)
        ):
            raise TypeError("approval deadline must be a monotonic number")
        deadline = float(self.deadline_monotonic)
        if not math.isfinite(deadline) or deadline < 0:
            raise ValueError("approval deadline must be finite and non-negative")
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(deepcopy(dict(self.arguments))),
        )
        object.__setattr__(self, "deadline_monotonic", deadline)


@runtime_checkable
class ApprovalHandler(Protocol):
    async def request(
        self,
        call: ToolInvocation,
        context: ApprovalRequestContext,
    ) -> ApprovalDecision: ...


@runtime_checkable
class EventBackedApprovalHandler(ApprovalHandler, Protocol):
    """Dedicated marker for handlers that own the requested event."""

    event_backed: Literal[True]


class LegacyApprovalHandler:
    """Deprecated adapter for the historical Boolean callback."""

    def __init__(self, callback: LegacyApprovalCallback) -> None:
        self._callback = callback

    async def request(
        self,
        call: ToolInvocation,
        context: ApprovalRequestContext,
    ) -> ApprovalDecision:
        granted = await self._callback(
            call.name,
            deepcopy(dict(context.arguments)),
            context.risk,
        )
        if type(granted) is not bool:
            raise TypeError("legacy approval callback must return bool")
        if granted:
            return ApprovalDecision(granted=True, code="approved")
        return ApprovalDecision(
            granted=False,
            code="rejected",
            reason="Rejected by approval handler",
        )


def adapt_approval_handler(
    handler: ApprovalHandler | LegacyApprovalCallback | None,
) -> ApprovalHandler | None:
    """Accept typed handlers while keeping one warned Boolean compatibility path."""
    if handler is None:
        return None
    request = inspect.getattr_static(handler, "request", None)
    if callable(request):
        return cast(ApprovalHandler, handler)
    if not callable(handler):
        raise TypeError("approval handler must implement request() or be callable")
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError) as error:
        raise TypeError("legacy approval handler must expose a signature") from error
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    variadic = any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if len(positional) != 3 and not variadic:
        raise TypeError("legacy approval handler must accept (tool_name, args, risk)")
    global _legacy_handler_warned
    if not _legacy_handler_warned:
        warnings.warn(
            "Boolean approval callbacks are deprecated; implement ApprovalHandler.request",
            DeprecationWarning,
            stacklevel=3,
        )
        _legacy_handler_warned = True
    return LegacyApprovalHandler(cast(LegacyApprovalCallback, handler))


class EventApprovalHandler:
    """Wait for an external tri-key decision on the runtime's own journal."""

    event_backed: Literal[True] = True

    async def request(
        self,
        call: ToolInvocation,
        context: ApprovalRequestContext,
    ) -> ApprovalDecision:
        journal = context.journal
        tool_context = context.tool_context
        if call.context != tool_context:
            raise ValueError("approval call and request context do not match")

        cursor = await journal.store.last_sequence(tool_context.session_id)
        events = await journal.open_subscription(
            tool_context.session_id,
            after_sequence=cursor,
        )
        if not isinstance(events, EventSubscription):
            raise TypeError("approval subscriptions must be explicitly closable")
        try:
            requested = require_stored_event(await context.request())
            assert requested.sequence is not None
            return await self._wait_for_decision(
                events,
                call,
                context,
                requested.sequence,
            )
        finally:
            await events.aclose()

    @staticmethod
    async def _wait_for_decision(
        events: Any,
        call: ToolInvocation,
        context: ApprovalRequestContext,
        requested_sequence: int,
    ) -> ApprovalDecision:
        expected = context.tool_context
        async for candidate in events:
            event = require_stored_event(candidate)
            assert event.sequence is not None
            if event.sequence <= requested_sequence:
                continue
            if event.type not in (
                EventType.TOOL_APPROVAL_APPROVED,
                EventType.TOOL_APPROVAL_REJECTED,
            ):
                continue
            if (
                event.turn_id != expected.turn_id
                or event.tool_call_id != expected.tool_call_id
                or event.tool_name != call.name
            ):
                continue
            await context.observe(event)
            if event.type == EventType.TOOL_APPROVAL_APPROVED:
                return ApprovalDecision(
                    granted=True,
                    code="approved",
                    recorded=True,
                )
            code_by_error: dict[ApprovalErrorCode, ApprovalCode] = {
                "APPROVAL_REJECTED": "rejected",
                "APPROVAL_TIMEOUT": "timeout",
                "TOOL_CANCELLED": "cancelled",
                "APPROVAL_UNAVAILABLE": "unavailable",
            }
            return ApprovalDecision(
                granted=False,
                code=code_by_error[event.error_code],
                reason=event.reason,
                recorded=True,
            )
        raise RuntimeError("approval event subscription ended before a decision")


__all__ = [
    "ApprovalCode",
    "ApprovalDecision",
    "ApprovalErrorCode",
    "ApprovalHandler",
    "ApprovalRequestContext",
    "EventApprovalHandler",
    "EventBackedApprovalHandler",
    "LegacyApprovalCallback",
]
