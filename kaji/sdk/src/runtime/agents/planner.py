"""Policy-gated, bounded planning for provider tool-call batches."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
import logging
import math
import uuid
import warnings
from typing import Any, Awaitable, Callable, Dict, List, Optional, cast

from kaji.infra.events.schemas import (
    ToolApprovalApproved,
    ToolApprovalRejected,
    ToolApprovalRequested,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import (
    MissingToolIdentityError,
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
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


logger = logging.getLogger(__name__)

ToolExecutor = Callable[[ToolInvocation], Awaitable[Any]]
LegacyToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]
ApprovalHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]

_legacy_executor_warned = False
_NO_RESULT = object()


def _arguments_are_json_safe(value: Any, active: set[int]) -> bool:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return True
    if value_type is float:
        return math.isfinite(value)
    if value_type is dict:
        object_id = id(value)
        if object_id in active:
            return False
        active.add(object_id)
        try:
            return all(
                type(key) is str and _arguments_are_json_safe(item, active)
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

    @classmethod
    def from_execution(cls, outcome: _ToolExecutionOutcome) -> _TerminalDraft:
        if outcome.failure is None:
            return cls(result=outcome.result)
        return cls(
            error=outcome.failure.error,
            fields={
                "error_code": outcome.failure.error_code,
                "retryable": outcome.failure.retryable,
                "outcome": outcome.failure.outcome,
            },
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


class ToolPlanner:
    """Validate, gate, and execute tools through a bounded controller."""

    def __init__(
        self,
        executor: ToolExecutor | LegacyToolExecutor,
        *,
        policy: Optional[ToolPolicy] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        specs: Optional[Dict[str, ToolSpec]] = None,
        controller: ToolExecutionController | None = None,
        execution_limits: ToolExecutionLimits | None = None,
        idempotency_ledger: ToolIdempotencyLedger | None = None,
    ):
        if controller is not None and (
            execution_limits is not None or idempotency_ledger is not None
        ):
            raise ValueError(
                "controller cannot be combined with execution_limits or idempotency_ledger"
            )
        self.executor = _adapt_executor(executor)
        self.policy = policy
        self.approval_handler = approval_handler
        self._specs: Dict[str, ToolSpec] = {
            name: _snapshot_tool_spec(spec) for name, spec in (specs or {}).items()
        }
        self._schema_validator = ToolSchemaValidator(self._specs)
        self.controller = controller or ToolExecutionController(
            limits=execution_limits,
            ledger=idempotency_ledger,
        )

    async def execute_scatter_gather(
        self,
        session_id: str,
        tool_calls: List[Dict[str, Any]],
        emit_event: Callable[[Any], Awaitable[None]],
        *,
        turn_id: str,
        turn_context: TurnContext,
        cancellation_token: CancellationToken,
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
        plumbing_errors: list[Exception] = []

        # Request records are attempted sequentially in provider order. A
        # failed append excludes only that call; accepted siblings continue.
        for item in prepared:
            try:
                await emit_event(
                    ToolCallRequested(
                        session_id=session_id,
                        tool_name=item.call["name"],
                        tool_args=item.tool_args,
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
                item.terminal = await self._preflight(item, session_id, emit_event)
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
                call_id = uuid.uuid4().hex
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
            tool_args = raw_args
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
        emit_event: Callable[[Any], Awaitable[None]],
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
            except ToolPolicyViolation as error:
                return _TerminalDraft(error=str(error))

        risk = item.spec.risk
        if self.policy is None or not self.policy.requires_approval(tool_name, risk):
            return None

        await emit_event(
            ToolApprovalRequested(
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=item.context.tool_call_id,
                tool_args=item.tool_args,
                risk=risk,
                metadata=item.metadata,
            )
        )
        approved = False
        if self.approval_handler is not None:
            try:
                approved = await self.approval_handler(tool_name, item.tool_args, risk)
            except Exception:
                logger.exception("Tool approval handler failed: %s", tool_name)
                await emit_event(
                    ToolApprovalRejected(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=item.context.tool_call_id,
                        reason="Approval handler unavailable",
                        metadata=item.metadata,
                    )
                )
                return _TerminalDraft(
                    error="Tool approval unavailable",
                    fields={
                        "error_code": "APPROVAL_UNAVAILABLE",
                        "retryable": False,
                        "outcome": "not_started",
                    },
                )

        if not approved:
            reason = (
                "No approval handler registered"
                if self.approval_handler is None
                else "Rejected by approval handler"
            )
            await emit_event(
                ToolApprovalRejected(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=item.context.tool_call_id,
                    reason=reason,
                    metadata=item.metadata,
                )
            )
            return _TerminalDraft(error=f"Tool approval rejected: {reason}")

        await emit_event(
            ToolApprovalApproved(
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=item.context.tool_call_id,
                metadata=item.metadata,
            )
        )
        return None

    async def _run_group(
        self,
        group: list[_PreparedCall],
        session_id: str,
        emit_event: Callable[[Any], Awaitable[None]],
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
        emit_event: Callable[[Any], Awaitable[None]],
    ) -> _ToolExecutionOutcome:
        async def emit_started() -> None:
            await emit_event(
                ToolCallStarted(
                    session_id=session_id,
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
            logger.error(
                "Tool execution failed: %s",
                item.call["name"],
                exc_info=(type(cause), cause, cause.__traceback__),
            )
        return outcome

    async def _emit_terminal(
        self,
        item: _PreparedCall,
        session_id: str,
        emit_event: Callable[[Any], Awaitable[None]],
    ) -> None:
        terminal = item.terminal
        if terminal is None:
            raise RuntimeError("tool call is missing a terminal draft")
        if terminal.error is None:
            await emit_event(
                ToolCallCompleted(
                    session_id=session_id,
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
