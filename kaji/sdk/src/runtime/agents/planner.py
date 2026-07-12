"""Policy-gated, bounded planning for provider tool-call batches."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import inspect
import json
import logging
import math
import warnings
from typing import Any, Awaitable, Callable, Dict, List, Optional, cast

from kaji.core.safe_logging import log_no_throw
from kaji.infra.events.json import canonical_json
from kaji.infra.events.schemas import (
    MAX_DURABLE_TOOL_ARGUMENT_BYTES,
    NewKajiEvent,
    StoredKajiEvent,
    ToolApprovalApproved,
    ToolApprovalRejected,
    ToolApprovalRequested,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
    event_defaults,
    require_stored_event,
    revalidate_stored_event,
)
from kaji.infra.events.protocols import EventJournal
from kaji.infra.events.types import EventType
from kaji.runtime.agents.approval import (
    ApprovalCode,
    ApprovalDecision,
    ApprovalErrorCode,
    ApprovalHandler,
    ApprovalRequestContext,
    LegacyApprovalCallback,
    adapt_approval_handler,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import (
    MissingToolIdentityError,
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.limits import TurnTimeoutError
from kaji.runtime.context import _copy_metadata_snapshot
from kaji.runtime.tools.errors import (
    ToolArgumentValidationError,
    UnclassifiedToolRiskError,
    validation_failure_fields,
)
from kaji.runtime.tools.execution import (
    ToolExecutionController,
    ToolExecutionLimits,
    _ToolExecutionOutcome,
)
from kaji.runtime.tools.idempotency import ToolIdempotencyLedger
from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
from kaji.runtime.tools.registry import ToolSpec, _snapshot_tool_spec
from kaji.runtime.tools.validation import ToolSchemaValidator
from kaji.runtime.determinism import (
    Clock,
    IdFactory,
    SYSTEM_CLOCK,
    SYSTEM_ID_FACTORY,
)


logger = logging.getLogger(__name__)

ToolExecutor = Callable[[ToolInvocation], Awaitable[Any]]
LegacyToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]

_legacy_executor_warned = False
_NO_RESULT = object()


class JournalEventEmitter:
    """Explicitly bind standalone planner events to one journal object."""

    def __init__(
        self,
        journal: EventJournal,
        *,
        before_commit: Callable[[NewKajiEvent], Awaitable[None]] | None = None,
        observer: Callable[[StoredKajiEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.journal = journal
        self._before_commit = before_commit
        self._observer = observer

    async def __call__(self, event: NewKajiEvent) -> StoredKajiEvent:
        if self._before_commit is not None:
            await self._before_commit(event)
        stored = await self.journal.commit(event)
        if self._observer is not None:
            await self._observer(stored)
        return stored

    async def observe_stored(self, event: StoredKajiEvent) -> None:
        if self._observer is not None:
            await self._observer(event)


def _require_approval_boundary(
    emit_event: Callable[[Any], Awaitable[Any]],
    journal: EventJournal | None,
) -> EventJournal:
    if journal is None:
        raise ValueError("approval_journal is required for approval-gated tools")
    if getattr(emit_event, "journal", None) is not journal or not callable(
        getattr(emit_event, "observe_stored", None)
    ):
        raise ValueError(
            "approval event emitter must be explicitly bound to approval_journal"
        )
    return journal


def _arguments_are_json_safe(value: Any, active: set[int]) -> bool:
    value_type = type(value)
    if value is None or value_type in (bool, int):
        return True
    if value_type is str:
        return not any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if value_type is float:
        return math.isfinite(value)
    if value_type is dict:
        object_id = id(value)
        if object_id in active:
            return False
        active.add(object_id)
        try:
            return all(
                type(key) is str
                and _arguments_are_json_safe(key, active)
                and _arguments_are_json_safe(item, active)
                for key, item in value.items()
            )
        finally:
            active.remove(object_id)
    if value_type is list:
        object_id = id(value)
        if object_id in active:
            return False
        active.add(object_id)
        try:
            return all(_arguments_are_json_safe(item, active) for item in value)
        finally:
            active.remove(object_id)
    return False


def _adapt_executor(
    executor: ToolExecutor | LegacyToolExecutor,
) -> ToolExecutor:
    """Adapt the pre-beta two-argument executor without exception probing."""
    try:
        signature = inspect.signature(executor)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "tool executor must expose an inspectable one-argument signature"
        ) from error
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    ):
        raise TypeError("variadic tool executors are not supported")
    if len(positional) == 1:
        return cast(ToolExecutor, executor)
    if len(positional) == 2:
        legacy_executor = cast(LegacyToolExecutor, executor)
        global _legacy_executor_warned
        if not _legacy_executor_warned:
            warnings.warn(
                "two-argument tool executors are deprecated; accept ToolInvocation",
                DeprecationWarning,
                stacklevel=3,
            )
            _legacy_executor_warned = True

        async def legacy_adapter(invocation: ToolInvocation) -> Any:
            return await legacy_executor(
                invocation.name,
                dict(invocation.arguments),
            )

        return legacy_adapter
    raise TypeError("tool executor must accept ToolInvocation")


@dataclass(slots=True)
class _TerminalDraft:
    result: Any = _NO_RESULT
    error: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    turn_timeout: TurnTimeoutError | None = None

    @classmethod
    def from_execution(cls, outcome: _ToolExecutionOutcome) -> _TerminalDraft:
        if outcome.failure is None:
            return cls(result=outcome.result)
        if outcome.failure.error_code in {
            "INVALID_DURABLE_VALUE",
            "EVENT_PAYLOAD_TOO_LARGE",
        }:
            return cls(
                error="Invalid tool result",
                fields={
                    "error_code": "INVALID_TOOL_RESULT",
                    "retryable": False,
                    "outcome": "unknown",
                },
            )
        timeout = (
            TurnTimeoutError(
                phase="tool",
                retryable=outcome.failure.retryable,
                outcome=outcome.failure.outcome,
            )
            if outcome.failure.turn_timeout
            else None
        )
        return cls(
            error=outcome.failure.error,
            fields={
                "error_code": outcome.failure.error_code,
                "retryable": outcome.failure.retryable,
                "outcome": outcome.failure.outcome,
            },
            turn_timeout=timeout,
        )


@dataclass(slots=True)
class _PreparedCall:
    index: int
    call: dict[str, Any]
    context: ToolExecutionContext
    spec: ToolSpec
    tool_args: dict[str, Any]
    metadata: Any
    validation_error: ToolArgumentValidationError | None = None
    terminal: _TerminalDraft | None = None
    recording_error: Exception | None = None

    @property
    def eligible(self) -> bool:
        return self.recording_error is None and self.terminal is None


class _ApprovalRequestGate:
    """Seal one canonical request and its externally persisted decision."""

    def __init__(
        self,
        event: ToolApprovalRequested,
        journal: EventJournal,
        emit: Callable[[Any], Awaitable[Any]],
        observe: Callable[[StoredKajiEvent], Awaitable[None]],
    ) -> None:
        self._event = event.model_copy(deep=True)
        self._journal = journal
        self._emit = emit
        self._observe = observe
        self._handler_called = False
        self._sealed = False
        self._stored: StoredKajiEvent | None = None
        self._observed: StoredKajiEvent | None = None

    @property
    def requested(self) -> bool:
        return self._stored is not None

    async def request(self) -> StoredKajiEvent:
        """Handler-facing exactly-once, no-argument request operation."""
        if self._sealed:
            raise RuntimeError("approval request operation is closed")
        if self._handler_called:
            raise RuntimeError("approval request was already attempted")
        self._handler_called = True
        return await self._commit()

    async def ensure_requested(self) -> StoredKajiEvent:
        """Runtime-owned idempotent recovery for pre-cancel and failed handlers."""
        if self._stored is not None:
            return self._stored
        return await self._commit()

    def seal(self) -> None:
        self._sealed = True

    async def _commit(self) -> StoredKajiEvent:
        stored = await self._persist_exact(self._event)
        if self._stored is not None and (
            self._stored.id != stored.id or self._stored.sequence != stored.sequence
        ):
            raise RuntimeError("approval request was persisted more than once")
        self._stored = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def _persist_exact(self, event: NewKajiEvent) -> StoredKajiEvent:
        stored = require_stored_event(await self._emit(event.model_copy(deep=True)))
        assert stored.sequence is not None
        expected = event.model_dump(mode="json", exclude={"sequence"})
        actual = stored.model_dump(mode="json", exclude={"sequence"})
        if actual != expected:
            raise ValueError("approval event emitter altered the canonical event")
        persisted = [
            revalidate_stored_event(item)
            for item in await self._journal.store.get_events(
                stored.session_id,
                after_sequence=stored.sequence - 1,
                limit=1,
            )
        ]
        if (
            len(persisted) != 1
            or persisted[0].sequence != stored.sequence
            or persisted[0].model_dump(mode="json") != stored.model_dump(mode="json")
        ):
            raise ValueError(
                "approval journal and event emitter must share one boundary"
            )
        return stored.model_copy(deep=True)

    def _matches_request(self, event: StoredKajiEvent) -> bool:
        requested = self._stored
        return (
            requested is not None
            and event.type
            in (
                EventType.TOOL_APPROVAL_APPROVED,
                EventType.TOOL_APPROVAL_REJECTED,
            )
            and event.session_id == requested.session_id
            and event.turn_id == requested.turn_id
            and event.tool_name == requested.tool_name
            and event.tool_call_id == requested.tool_call_id
        )

    @staticmethod
    def _decision_from_event(event: StoredKajiEvent) -> ApprovalDecision:
        if event.type == EventType.TOOL_APPROVAL_APPROVED:
            return ApprovalDecision(True, "approved", recorded=True)
        if event.type != EventType.TOOL_APPROVAL_REJECTED:
            raise TypeError("event is not an approval decision")
        code_by_error: dict[ApprovalErrorCode, ApprovalCode] = {
            "APPROVAL_REJECTED": "rejected",
            "APPROVAL_TIMEOUT": "timeout",
            "TURN_TIMEOUT": "timeout",
            "TOOL_CANCELLED": "cancelled",
            "APPROVAL_UNAVAILABLE": "unavailable",
        }
        return ApprovalDecision(
            False,
            code_by_error[event.error_code],
            event.reason,
            recorded=True,
        )

    async def observe(self, candidate: StoredKajiEvent) -> None:
        event = require_stored_event(candidate)
        requested = self._stored
        if requested is None or requested.sequence is None or event.sequence is None:
            raise RuntimeError("approval decision cannot precede its request")
        if event.sequence <= requested.sequence:
            raise ValueError("approval decision must follow its exact request sequence")
        if not self._matches_request(event):
            raise ValueError("approval decision correlation does not match its request")
        persisted = [
            revalidate_stored_event(item)
            for item in await self._journal.store.get_events(
                event.session_id,
                after_sequence=event.sequence - 1,
                limit=1,
            )
        ]
        if (
            len(persisted) != 1
            or persisted[0].sequence != event.sequence
            or persisted[0].model_dump(mode="json") != event.model_dump(mode="json")
        ):
            raise ValueError("approval decision must use the canonical journal")
        if self._observed is not None:
            if (
                self._observed.id == event.id
                and self._observed.sequence == event.sequence
            ):
                return
            raise RuntimeError("approval decision was observed more than once")
        await self._observe(event)
        self._observed = event.model_copy(deep=True)

    def observed_decision(self) -> ApprovalDecision | None:
        if self._observed is None:
            return None
        return self._decision_from_event(self._observed)

    def observed_error_code(self) -> ApprovalErrorCode | None:
        if (
            self._observed is None
            or self._observed.type != EventType.TOOL_APPROVAL_REJECTED
        ):
            return None
        return self._observed.error_code

    async def resolve_framework_loss(
        self,
        decision: ApprovalDecision,
        *,
        error_code: ApprovalErrorCode | None = None,
    ) -> ApprovalDecision:
        """Fence a framework loss, then choose the first durable decision."""
        requested = self._stored
        if requested is None or requested.sequence is None or decision.reason is None:
            raise RuntimeError("approval loss cannot be fenced before its request")
        assert requested.turn_id is not None
        error_by_code: dict[ApprovalCode, ApprovalErrorCode] = {
            "cancelled": "TOOL_CANCELLED",
            "timeout": "APPROVAL_TIMEOUT",
            "rejected": "APPROVAL_REJECTED",
            "unavailable": "APPROVAL_UNAVAILABLE",
            "approved": "APPROVAL_UNAVAILABLE",
        }
        fence = await self._persist_exact(
            ToolApprovalRejected(
                session_id=requested.session_id,
                turn_id=requested.turn_id,
                tool_name=requested.tool_name,
                tool_call_id=requested.tool_call_id,
                error_code=error_code or error_by_code[decision.code],
                reason=decision.reason,
                metadata=deepcopy(requested.metadata),
            )
        )
        assert fence.sequence is not None
        suffix = [
            revalidate_stored_event(event)
            for event in await self._journal.store.get_events(
                requested.session_id,
                after_sequence=requested.sequence,
                limit=fence.sequence - requested.sequence,
            )
        ]
        for event in suffix:
            if event.sequence is None or event.sequence > fence.sequence:
                break
            if not self._matches_request(event):
                continue
            await self.observe(event)
            return self._decision_from_event(event)
        raise RuntimeError("approval fence did not persist a matching decision")


class ToolPlanner:
    """Validate, gate, and execute tools through a bounded controller."""

    def __init__(
        self,
        executor: ToolExecutor | LegacyToolExecutor,
        *,
        policy: Optional[ToolPolicy] = None,
        approval_handler: ApprovalHandler | LegacyApprovalCallback | None = None,
        specs: Optional[Dict[str, ToolSpec]] = None,
        controller: ToolExecutionController | None = None,
        execution_limits: ToolExecutionLimits | None = None,
        idempotency_ledger: ToolIdempotencyLedger | None = None,
        id_factory: IdFactory | None = None,
        clock: Clock | None = None,
    ):
        if controller is not None and (
            execution_limits is not None or idempotency_ledger is not None
        ):
            raise ValueError(
                "controller cannot be combined with execution_limits or idempotency_ledger"
            )
        self.executor = _adapt_executor(executor)
        self.policy = policy
        self.approval_handler = adapt_approval_handler(approval_handler)
        self._specs: Dict[str, ToolSpec] = {
            name: _snapshot_tool_spec(spec) for name, spec in (specs or {}).items()
        }
        self._schema_validator = ToolSchemaValidator(self._specs)
        self._id_factory = id_factory or SYSTEM_ID_FACTORY
        self._clock = clock or SYSTEM_CLOCK
        self.controller = controller or ToolExecutionController(
            limits=execution_limits,
            ledger=idempotency_ledger,
            clock=self._clock.now_monotonic,
        )

    async def execute_batch(
        self,
        session_id: str,
        tool_calls: List[Dict[str, Any]],
        emit_event: Callable[[Any], Awaitable[Any]],
        *,
        turn_id: str,
        turn_context: TurnContext,
        cancellation_token: CancellationToken,
        approval_journal: EventJournal | None = None,
    ) -> List[Dict[str, Any]]:
        with event_defaults(self._id_factory, self._clock):
            return await self._execute_batch(
                session_id,
                tool_calls,
                emit_event,
                turn_id=turn_id,
                turn_context=turn_context,
                cancellation_token=cancellation_token,
                approval_journal=approval_journal,
            )

    async def _execute_batch(
        self,
        session_id: str,
        tool_calls: List[Dict[str, Any]],
        emit_event: Callable[[Any], Awaitable[Any]],
        *,
        turn_id: str,
        turn_context: TurnContext,
        cancellation_token: CancellationToken,
        approval_journal: EventJournal | None = None,
    ) -> List[Dict[str, Any]]:
        """Execute one provider batch with ordered request and terminal events.

        Per-call journal failures are collected so accepted siblings still
        settle. They are raised together after every possible terminal append;
        a parent ``CancelledError`` still propagates immediately.
        """
        resolved_context = TurnContext(
            principal_id=turn_context.principal_id,
            request_id=turn_context.request_id,
            trace_id=turn_context.trace_id,
            deadline_monotonic=turn_context.deadline_monotonic,
            db=turn_context.db,
            metadata=_copy_metadata_snapshot(turn_context.metadata),
            id_factory=self._id_factory,
        )
        if resolved_context.principal_id is None:
            raise MissingToolIdentityError()
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError("turn_id must be a non-empty string")

        normalized = self._prepare_calls(tool_calls)
        prepared = [
            self._build_prepared(
                index,
                call,
                ToolExecutionContext(
                    principal_id=resolved_context.principal_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    request_id=resolved_context.request_id,
                    trace_id=resolved_context.trace_id,
                    tool_call_id=call["id"],
                    idempotency_key=f"{session_id}:{call['id']}",
                    cancellation_token=cancellation_token,
                    deadline_monotonic=resolved_context.deadline_monotonic,
                    db=resolved_context.db,
                    metadata=_copy_metadata_snapshot(resolved_context.metadata),
                ),
            )
            for index, call in enumerate(normalized)
        ]
        if self.policy is not None:
            for item in prepared:
                aliases = [item.spec.catalog_name] if item.spec.catalog_name else []
                if self.policy.is_allowed_any([item.call["name"], *aliases]) and (
                    self.policy.requires_approval(item.call["name"], item.spec.risk)
                ):
                    _require_approval_boundary(emit_event, approval_journal)
                    break
        plumbing_errors: list[Exception] = []

        # Request records are attempted sequentially in provider order. A
        # failed append excludes only that call; accepted siblings continue.
        for item in prepared:
            try:
                await emit_event(
                    ToolCallRequested(
                        session_id=session_id,
                        turn_id=item.context.turn_id,
                        tool_name=item.call["name"],
                        tool_args=deepcopy(item.tool_args),
                        tool_call_id=item.context.tool_call_id,
                        metadata=item.metadata,
                    )
                )
            except Exception as error:
                item.recording_error = error
                plumbing_errors.append(error)

        # Schema, policy, and approval checks are deterministic and ordered.
        for item in prepared:
            if item.recording_error is not None:
                continue
            try:
                item.terminal = await self._preflight(
                    item,
                    session_id,
                    emit_event,
                    approval_journal,
                )
            except Exception as error:
                item.recording_error = error
                plumbing_errors.append(error)

        # A parallel-safe run is bounded by the controller. Every unmarked
        # tool is an exclusive barrier, including while a timed-out handler is
        # still physically running.
        safe_group: list[_PreparedCall] = []
        for item in prepared:
            if item.spec.parallel_safe:
                if item.eligible:
                    safe_group.append(item)
                continue
            await self._run_group(safe_group, session_id, emit_event, plumbing_errors)
            safe_group.clear()
            if item.eligible:
                await self._run_group([item], session_id, emit_event, plumbing_errors)
        await self._run_group(safe_group, session_id, emit_event, plumbing_errors)

        results: list[dict[str, Any] | None] = [None] * len(prepared)
        for item in prepared:
            if item.recording_error is not None or item.terminal is None:
                continue
            results[item.index] = self._result_payload(item)
            try:
                await self._emit_terminal(item, session_id, emit_event)
            except Exception as error:
                item.recording_error = error
                plumbing_errors.append(error)

        if plumbing_errors:
            raise ExceptionGroup(
                f"{len(plumbing_errors)} of {len(prepared)} tool call(s) failed to record their events",
                plumbing_errors,
            )
        turn_timeouts = [
            item.terminal.turn_timeout
            for item in prepared
            if item.terminal is not None and item.terminal.turn_timeout is not None
        ]
        if turn_timeouts:
            raise next(
                (timeout for timeout in turn_timeouts if timeout.outcome == "unknown"),
                turn_timeouts[0],
            )
        if any(result is None for result in results):
            raise RuntimeError("tool execution did not produce a terminal result")
        return cast(List[Dict[str, Any]], results)

    def _prepare_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Resolve and validate the complete batch before lifecycle emission."""
        prepared: List[Dict[str, Any]] = []
        call_ids: set[str] = set()
        for call in tool_calls:
            raw_name = call.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise UnclassifiedToolRiskError("unknown")
            tool_name = raw_name.strip()
            spec = self._specs.get(tool_name)
            if spec is None or spec.risk is None:
                raise UnclassifiedToolRiskError(tool_name)
            if not spec.enabled:
                raise ToolPolicyViolation(f"Tool not permitted: {tool_name}")
            raw_arguments = call.get("arguments", {})
            if isinstance(raw_arguments, dict) and not _arguments_are_json_safe(
                raw_arguments, set()
            ):
                raise ToolArgumentValidationError.non_json_value(tool_name)

            raw_call_id = call.get("id")
            if raw_call_id is None:
                call_id = self._id_factory.next("tool_call")
            elif not isinstance(raw_call_id, str) or not raw_call_id.strip():
                raise ValueError("tool call id must be a non-empty string")
            else:
                call_id = raw_call_id
            if call_id in call_ids:
                raise ValueError(f"duplicate tool call id: {call_id}")
            call_ids.add(call_id)
            prepared.append({**call, "id": call_id, "name": tool_name})
        return prepared

    def _build_prepared(
        self,
        index: int,
        call: dict[str, Any],
        context: ToolExecutionContext,
    ) -> _PreparedCall:
        tool_name = call["name"]
        raw_args = call.get("arguments", {})
        validation_error: ToolArgumentValidationError | None = None
        if not isinstance(raw_args, dict):
            tool_args = {"__parse_error": "invalid arguments"}
            validation_error = ToolArgumentValidationError.non_object(tool_name)
        elif isinstance(raw_args.get("__parse_error"), str):
            tool_args = {"__parse_error": "invalid JSON"}
            validation_error = ToolArgumentValidationError.parse_error(tool_name)
        else:
            try:
                serialized_args = canonical_json(raw_args, subject="tool arguments")
                arguments_size = len(serialized_args.encode("utf-8"))
                detached_args = json.loads(serialized_args)
            except (TypeError, ValueError, UnicodeError):
                tool_args = {"__parse_error": "invalid arguments"}
                validation_error = ToolArgumentValidationError.non_json_value(tool_name)
            else:
                if arguments_size > MAX_DURABLE_TOOL_ARGUMENT_BYTES:
                    tool_args = {"__parse_error": "payload too large"}
                    validation_error = ToolArgumentValidationError.oversize(tool_name)
                else:
                    tool_args = detached_args
        spec = self._specs[tool_name]
        metadata: Any = {"catalog_name": spec.catalog_name} if spec.catalog_name else {}
        return _PreparedCall(
            index=index,
            call=call,
            context=context,
            spec=spec,
            tool_args=tool_args,
            metadata=metadata,
            validation_error=validation_error,
        )

    async def _preflight(
        self,
        item: _PreparedCall,
        session_id: str,
        emit_event: Callable[[Any], Awaitable[Any]],
        approval_journal: EventJournal | None,
    ) -> _TerminalDraft | None:
        tool_name = item.call["name"]
        validation_error = item.validation_error
        if validation_error is None:
            try:
                self._schema_validator.validate(tool_name, item.tool_args)
            except ToolArgumentValidationError as error:
                validation_error = error
        if validation_error is not None:
            return _TerminalDraft(
                error=validation_error.message,
                fields=validation_failure_fields(validation_error),
            )

        aliases = [item.spec.catalog_name] if item.spec.catalog_name else []
        if self.policy is not None:
            try:
                self.policy.enforce_any(tool_name, aliases)
            except ToolPolicyViolation:
                return _TerminalDraft(
                    error="Tool not permitted",
                    fields={
                        "error_code": "TOOL_NOT_ALLOWED",
                        "retryable": False,
                        "outcome": "not_started",
                    },
                )

        risk = item.spec.risk
        if self.policy is None or not self.policy.requires_approval(tool_name, risk):
            return None
        if risk is None:
            raise RuntimeError("approval-required tools must have a classified risk")
        approval_journal = _require_approval_boundary(
            emit_event,
            approval_journal,
        )

        request_event = ToolApprovalRequested(
            session_id=session_id,
            turn_id=item.context.turn_id,
            tool_name=tool_name,
            tool_call_id=item.context.tool_call_id,
            tool_args=deepcopy(item.tool_args),
            risk=risk,
            metadata=deepcopy(item.metadata),
        )
        observe_stored = getattr(emit_event, "observe_stored", None)
        assert callable(observe_stored)

        request_gate = _ApprovalRequestGate(
            request_event,
            approval_journal,
            emit_event,
            observe_stored,
        )
        handler = self.approval_handler
        event_backed = (
            handler is not None and getattr(handler, "event_backed", False) is True
        )
        if not event_backed:
            await request_gate.request()

        effective_deadline = self.controller.approval_deadline(
            item.context.deadline_monotonic
        )
        deadline = effective_deadline.value
        framework_loss = False
        outer_timeout = False
        if item.context.cancellation_token.is_cancelled:
            framework_loss = event_backed
            decision = ApprovalDecision(
                granted=False,
                code="cancelled",
                reason="Tool approval cancelled",
            )
        elif self.controller.deadline_expired(deadline):
            framework_loss = event_backed
            outer_timeout = effective_deadline.outer
            decision = ApprovalDecision(
                granted=False,
                code="timeout",
                reason="Tool approval timed out",
            )
        elif handler is None:
            decision = ApprovalDecision(
                granted=False,
                code="unavailable",
                reason="No approval handler registered",
            )
        else:
            invocation = ToolInvocation(
                name=tool_name,
                arguments=item.tool_args,
                context=item.context,
            )
            approval_context = ApprovalRequestContext(
                tool_context=item.context,
                risk=risk,
                arguments=item.tool_args,
                journal=approval_journal,
                request=request_gate.request,
                observe=request_gate.observe,
                deadline_monotonic=deadline,
            )
            request_task = self.controller.start_approval(
                item.context.tool_call_id,
                lambda: handler.request(invocation, approval_context),
            )
            if request_task is None:
                decision = ApprovalDecision(
                    granted=False,
                    code="unavailable",
                    reason="Approval handler capacity exhausted",
                )
            else:
                cancellation_task = asyncio.create_task(
                    item.context.cancellation_token.wait()
                )
                try:
                    done = await self.controller.wait_until_deadline(
                        {request_task, cancellation_task}, deadline
                    )
                    # A fully observed durable decision wins a simultaneous
                    # caller cancellation. Cancellation wins only while the
                    # handler is still physically unresolved.
                    if request_task.done():
                        try:
                            decision = request_task.result()
                            if not isinstance(decision, ApprovalDecision):
                                raise TypeError(
                                    "approval handler must return ApprovalDecision"
                                )
                            if event_backed and not request_gate.requested:
                                raise RuntimeError(
                                    "event-backed approval handler returned before "
                                    "recording its request"
                                )
                            observed = request_gate.observed_decision()
                            if observed is not None:
                                decision = observed
                                outer_timeout = (
                                    request_gate.observed_error_code() == "TURN_TIMEOUT"
                                )
                            elif decision.recorded:
                                raise RuntimeError(
                                    "recorded approval decision does not match the journal"
                                )
                        except BaseException as error:
                            log_no_throw(
                                logger,
                                logging.ERROR,
                                "Tool approval handler failed: %s (%s; details redacted)",
                                tool_name,
                                type(error).__name__,
                            )
                            decision = ApprovalDecision(
                                granted=False,
                                code="unavailable",
                                reason="Approval handler unavailable",
                            )
                    elif (
                        cancellation_task in done
                        or item.context.cancellation_token.is_cancelled
                    ):
                        framework_loss = event_backed
                        decision = ApprovalDecision(
                            False,
                            "cancelled",
                            "Tool approval cancelled",
                        )
                    else:
                        framework_loss = event_backed
                        outer_timeout = effective_deadline.outer
                        decision = ApprovalDecision(
                            False,
                            "timeout",
                            "Tool approval timed out",
                        )
                finally:
                    request_gate.seal()
                    cancellation_task.cancel()
                    try:
                        await cancellation_task
                    except asyncio.CancelledError:
                        pass
                    if not request_task.done():
                        request_task.cancel()
        request_gate.seal()
        await request_gate.ensure_requested()
        if framework_loss:
            decision = await request_gate.resolve_framework_loss(
                decision,
                error_code="TURN_TIMEOUT" if outer_timeout else None,
            )
        observed = request_gate.observed_decision()
        if observed is not None:
            decision = observed
            outer_timeout = request_gate.observed_error_code() == "TURN_TIMEOUT"
        elif decision.recorded:
            decision = ApprovalDecision(
                granted=False,
                code="unavailable",
                reason="Approval handler unavailable",
            )

        if decision.granted:
            if not decision.recorded:
                await emit_event(
                    ToolApprovalApproved(
                        session_id=session_id,
                        turn_id=item.context.turn_id,
                        tool_name=tool_name,
                        tool_call_id=item.context.tool_call_id,
                        metadata=item.metadata,
                    )
                )
            return None

        if decision.code == "rejected":
            failure_fields: tuple[ApprovalErrorCode, bool, str] = (
                "APPROVAL_REJECTED",
                False,
                "Tool approval rejected",
            )
        elif decision.code == "timeout":
            failure_fields = (
                "TURN_TIMEOUT" if outer_timeout else "APPROVAL_TIMEOUT",
                True,
                (
                    "Turn deadline exceeded during approval"
                    if outer_timeout
                    else "Tool approval timed out"
                ),
            )
        elif decision.code == "cancelled":
            failure_fields = (
                "TOOL_CANCELLED",
                True,
                "Tool approval cancelled",
            )
        else:
            failure_fields = (
                "APPROVAL_UNAVAILABLE",
                False,
                "Tool approval unavailable",
            )
        error_code, retryable, error = failure_fields
        assert decision.reason is not None
        if not decision.recorded:
            await emit_event(
                ToolApprovalRejected(
                    session_id=session_id,
                    turn_id=item.context.turn_id,
                    tool_name=tool_name,
                    tool_call_id=item.context.tool_call_id,
                    error_code=error_code,
                    reason=decision.reason,
                    metadata=item.metadata,
                )
            )
        return _TerminalDraft(
            error=error,
            fields={
                "error_code": error_code,
                "retryable": retryable,
                "outcome": "not_started",
            },
            turn_timeout=(
                TurnTimeoutError(
                    phase="approval",
                    retryable=True,
                    outcome="not_started",
                )
                if outer_timeout and decision.code == "timeout"
                else None
            ),
        )

    async def _run_group(
        self,
        group: list[_PreparedCall],
        session_id: str,
        emit_event: Callable[[Any], Awaitable[Any]],
        plumbing_errors: list[Exception],
    ) -> None:
        if not group:
            return
        next_index = 0

        async def run_worker() -> None:
            nonlocal next_index
            while next_index < len(group):
                item = group[next_index]
                next_index += 1
                try:
                    outcome = await self._execute_prepared(item, session_id, emit_event)
                except Exception as error:
                    item.recording_error = error
                    plumbing_errors.append(error)
                else:
                    item.terminal = _TerminalDraft.from_execution(outcome)

        tasks = {
            asyncio.create_task(run_worker())
            for _ in range(min(len(group), self.controller.limits.max_parallel))
        }
        try:
            done, _ = await asyncio.wait(tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)
            raise
        for task in done:
            try:
                task.result()
            except asyncio.CancelledError:
                raise

    async def _execute_prepared(
        self,
        item: _PreparedCall,
        session_id: str,
        emit_event: Callable[[Any], Awaitable[Any]],
    ) -> _ToolExecutionOutcome:
        async def emit_started() -> None:
            await emit_event(
                ToolCallStarted(
                    session_id=session_id,
                    turn_id=item.context.turn_id,
                    tool_name=item.call["name"],
                    tool_call_id=item.context.tool_call_id,
                    metadata=item.metadata,
                )
            )

        outcome = await self.controller.execute(
            ToolInvocation(
                name=item.call["name"],
                arguments=item.tool_args,
                context=item.context,
            ),
            item.spec,
            self.executor,
            emit_started,
        )
        if outcome.failure is not None and outcome.failure.cause is not None:
            cause = outcome.failure.cause
            log_no_throw(
                logger,
                logging.ERROR,
                "Tool execution failed: %s (%s; details redacted)",
                item.call["name"],
                type(cause).__name__,
            )
        return outcome

    async def _emit_terminal(
        self,
        item: _PreparedCall,
        session_id: str,
        emit_event: Callable[[Any], Awaitable[Any]],
    ) -> None:
        terminal = item.terminal
        if terminal is None:
            raise RuntimeError("tool call is missing a terminal draft")
        if terminal.error is None:
            await emit_event(
                ToolCallCompleted(
                    session_id=session_id,
                    turn_id=item.context.turn_id,
                    tool_name=item.call["name"],
                    tool_call_id=item.context.tool_call_id,
                    result=terminal.result,
                    metadata=item.metadata,
                )
            )
            return
        await emit_event(
            ToolCallFailed(
                session_id=session_id,
                turn_id=item.context.turn_id,
                tool_name=item.call["name"],
                tool_call_id=item.context.tool_call_id,
                error=terminal.error,
                metadata=item.metadata,
                **terminal.fields,
            )
        )

    def _result_payload(self, item: _PreparedCall) -> dict[str, Any]:
        terminal = item.terminal
        if terminal is None:
            raise RuntimeError("tool call is missing a terminal draft")
        payload = {"id": item.context.tool_call_id, "name": item.call["name"]}
        if terminal.error is None:
            return {**payload, "result": terminal.result}
        return {**payload, "error": terminal.error, **terminal.fields}
