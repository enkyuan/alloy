"""Bounded, cancellable tool execution shared across runtime turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import logging
import math
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Coroutine, Literal

from kaji.core.safe_logging import log_no_throw, log_redacted_failure
from kaji.infra.events.errors import DurableJsonLimitError, InvalidDurableValueError
from kaji.infra.events.json import durable_json_snapshot
from kaji.infra.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    NOOP_TRACE,
    TraceSink,
    metric_error_code,
    record_metric,
    span_end,
    span_record_error,
    start_span,
)
from kaji.runtime.context import ToolInvocation, _copy_metadata_snapshot
from kaji.runtime.determinism import (
    SYSTEM_TIMER_SCHEDULER,
    TimerScheduler,
)
from kaji.runtime.tools.idempotency import (
    IdempotencyCapacityExceeded,
    IdempotencyConflictError,
    InMemoryToolIdempotencyLedger,
    ToolIdempotencyClaim,
    ToolIdempotencyFailure,
    ToolIdempotencyLedger,
    ToolIdempotencyResolution,
)
from kaji.runtime.tools.registry import ToolSpec

if TYPE_CHECKING:
    from kaji.runtime.agents.cancellation import CancellationToken


ToolExecutor = Callable[[ToolInvocation], Awaitable[Any]]
StartedEmitter = Callable[[], Awaitable[None]]

_PUBLIC_EXECUTION_FAILURE = "Tool execution failed"
_PUBLIC_CANCELLED = "Tool execution cancelled"
_PUBLIC_TIMEOUT = "Tool execution timed out"
_PUBLIC_CAPACITY = "Tool execution capacity exhausted"
_PUBLIC_CONFLICT = "Tool invocation conflicts with an existing idempotency key"
_PUBLIC_INVALID_ARGUMENTS = "Invalid tool arguments"
_PUBLIC_INVALID_RESULT = "Invalid tool result"
_STARTED_LOOKUP_TIMEOUT_SECONDS = 0.1

logger = logging.getLogger(__name__)


def _integration_recovery_fields(value: object) -> dict[str, str]:
    from kaji.integrations.recovery import closed_recovery_fields  # noqa: PLC0415

    return closed_recovery_fields(value)


def _integration_transport_failure_fields(value: object) -> dict[str, str]:
    from kaji.integrations.recovery import (  # noqa: PLC0415
        closed_transport_failure_fields,
    )

    return closed_transport_failure_fields(value)


class ToolExecutionError(RuntimeError):
    """A handler-certified failure known to have produced no side effect."""

    error_code = "TOOL_EXECUTION_FAILED"
    retryable = True
    outcome: Literal["failed"] = "failed"

    def __init__(self) -> None:
        super().__init__(_PUBLIC_EXECUTION_FAILURE)


@dataclass(frozen=True, slots=True)
class ToolExecutionLimits:
    """Runtime-wide bounds for tool and approval execution."""

    max_parallel: int = 4
    timeout_seconds: float = 30.0
    approval_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if isinstance(self.max_parallel, bool) or not isinstance(
            self.max_parallel, int
        ):
            raise TypeError("max_parallel must be a positive integer")
        if self.max_parallel < 1:
            raise ValueError("max_parallel must be a positive integer")
        for name in ("timeout_seconds", "approval_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a positive number")
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be a positive number")
            object.__setattr__(self, name, float(value))


@dataclass(frozen=True, slots=True)
class _ToolExecutionFailure:
    """Planner-internal status plus an original cause for private logging."""

    error: str
    error_code: str
    retryable: bool
    outcome: Literal["not_started", "failed", "unknown"]
    reason_code: str | None = None
    recovery_code: str | None = None
    doc_url: str | None = None
    cause: BaseException | None = field(default=None, repr=False, compare=False)
    turn_timeout: bool = field(default=False, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _ToolExecutionOutcome:
    """Closed execution result consumed by the planner's terminal emitter."""

    result: Any | None = None
    failure: _ToolExecutionFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None


@dataclass(slots=True)
class _ActiveExecution:
    call_id: str
    task: asyncio.Task[Any]


@dataclass(slots=True)
class _PendingSetup:
    operation_id: int
    session_id: str
    call_id: str
    task: asyncio.Task[Any]
    settlement: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _PendingApproval:
    operation_id: int
    call_id: str
    task: asyncio.Task[Any]


@dataclass(frozen=True, slots=True)
class _Settlement:
    result: Any | None = None
    cause: BaseException | None = None


@dataclass(frozen=True, slots=True)
class _EffectiveDeadline:
    value: float
    outer: bool


def _ledger_failure(failure: _ToolExecutionFailure) -> ToolIdempotencyFailure:
    return ToolIdempotencyFailure(
        error=failure.error,
        error_code=failure.error_code,
        retryable=failure.retryable,
        outcome=failure.outcome,
        reason_code=failure.reason_code,
        recovery_code=failure.recovery_code,
        doc_url=failure.doc_url,
    )


def _from_resolution(
    resolution: ToolIdempotencyResolution,
) -> _ToolExecutionOutcome:
    if resolution.failure is None:
        return _ToolExecutionOutcome(result=resolution.result)
    failure = resolution.failure
    if failure.subject == "tool_result" and failure.error_code in {
        "INVALID_DURABLE_VALUE",
        "EVENT_PAYLOAD_TOO_LARGE",
    }:
        return _ToolExecutionOutcome(failure=_invalid_tool_result())
    return _ToolExecutionOutcome(
        failure=_ToolExecutionFailure(
            error=failure.error,
            error_code=failure.error_code,
            retryable=failure.retryable,
            outcome=failure.outcome,
            reason_code=failure.reason_code,
            recovery_code=failure.recovery_code,
            doc_url=failure.doc_url,
        )
    )


def _invalid_tool_result(
    cause: BaseException | None = None,
) -> _ToolExecutionFailure:
    return _ToolExecutionFailure(
        error=_PUBLIC_INVALID_RESULT,
        error_code="INVALID_TOOL_RESULT",
        retryable=False,
        outcome="unknown",
        cause=cause,
    )


def _durable_result_tombstone(
    error: InvalidDurableValueError | DurableJsonLimitError,
) -> ToolIdempotencyFailure:
    return ToolIdempotencyFailure(
        error="Invalid durable tool result",
        error_code=error.code,
        retryable=False,
        outcome="unknown",
        subject=error.subject,
    )


def _cancelled(*, started: bool) -> _ToolExecutionFailure:
    return _ToolExecutionFailure(
        error=_PUBLIC_CANCELLED,
        error_code="TOOL_CANCELLED",
        retryable=not started,
        outcome="unknown" if started else "not_started",
    )


def _timed_out(*, started: bool, outer: bool = False) -> _ToolExecutionFailure:
    return _ToolExecutionFailure(
        error="Turn deadline exceeded during tool" if outer else _PUBLIC_TIMEOUT,
        error_code="TURN_TIMEOUT" if outer else "TOOL_TIMEOUT",
        retryable=not started,
        outcome="unknown" if started else "not_started",
        turn_timeout=outer,
    )


async def _cancel_and_join(task: asyncio.Task[Any]) -> None:
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _cancel_acquisition(task: asyncio.Task[Any]) -> bool:
    """Cancel an owned acquisition task and report whether it acquired first."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return False
    return True


async def _cancel_operation(
    task: asyncio.Task[Any],
) -> tuple[bool, BaseException | None]:
    """Cancel a cooperative operation and consume its terminal state."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return False, None
    except BaseException as error:
        return True, error
    return True, None


class ToolExecutionController:
    """Own runtime-lifetime concurrency, cancellation, and idempotency state."""

    def __init__(
        self,
        limits: ToolExecutionLimits | None = None,
        ledger: ToolIdempotencyLedger | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        timer_scheduler: TimerScheduler = SYSTEM_TIMER_SCHEDULER,
        metrics_sink: MetricsSink = NOOP_METRICS,
        trace_sink: TraceSink = NOOP_TRACE,
    ) -> None:
        self.limits = limits if limits is not None else ToolExecutionLimits()
        self.ledger = ledger if ledger is not None else InMemoryToolIdempotencyLedger()
        self._clock = clock
        self._timer_scheduler = timer_scheduler
        self._metrics = metrics_sink
        self._trace = trace_sink
        self._semaphore = asyncio.Semaphore(self.limits.max_parallel)
        self._setup_semaphore = asyncio.Semaphore(self.limits.max_parallel)
        self._active: dict[tuple[str, str], _ActiveExecution] = {}
        self._pending_setup: dict[int, _PendingSetup] = {}
        self._next_setup_id = 0
        self._pending_approvals: dict[int, _PendingApproval] = {}
        self._next_approval_id = 0
        self._gate = asyncio.Condition()
        self._safe_claims = 0
        self._exclusive_active = False
        self._exclusive_waiters = 0

    def _start_setup(
        self,
        *,
        session_id: str,
        call_id: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> _PendingSetup:
        async def run() -> Any:
            async with self._setup_semaphore:
                return await operation()

        self._next_setup_id += 1
        pending = _PendingSetup(
            operation_id=self._next_setup_id,
            session_id=session_id,
            call_id=call_id,
            task=asyncio.create_task(run()),
        )
        self._pending_setup[pending.operation_id] = pending
        return pending

    def _finish_setup(self, pending: _PendingSetup) -> None:
        self._pending_setup.pop(pending.operation_id, None)

    def _detach_setup(
        self,
        pending: _PendingSetup,
        settle: Callable[[asyncio.Task[Any]], Awaitable[None]],
    ) -> None:
        pending.task.cancel()
        pending.settlement = asyncio.create_task(
            self._settle_detached_setup(pending, settle)
        )

    async def _settle_detached_setup(
        self,
        pending: _PendingSetup,
        settle: Callable[[asyncio.Task[Any]], Awaitable[None]],
    ) -> None:
        try:
            await settle(pending.task)
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Detached tool setup settlement failed",
                error,
            )
        finally:
            self._finish_setup(pending)

    def _continue_setup(self, pending: _PendingSetup) -> None:
        pending.settlement = asyncio.create_task(self._settle_background_setup(pending))

    async def _settle_background_setup(self, pending: _PendingSetup) -> None:
        try:
            await pending.task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            log_redacted_failure(
                logger, logging.ERROR, "Background tool setup failed", error
            )
        finally:
            self._finish_setup(pending)

    async def _claim_with_deadline(
        self,
        invocation: ToolInvocation,
        effective_deadline: _EffectiveDeadline,
    ) -> tuple[ToolIdempotencyClaim | None, _ToolExecutionFailure | None]:
        context = invocation.context
        deadline = effective_deadline.value
        pending = self._start_setup(
            session_id=context.session_id,
            call_id=context.tool_call_id,
            operation=lambda: self.ledger.claim(
                session_id=context.session_id,
                tool_call_id=context.tool_call_id,
                tool_name=invocation.name,
                tool_args=dict(invocation.arguments),
            ),
        )
        claim_task = pending.task
        cancel_task = asyncio.create_task(context.cancellation_token.wait())
        try:
            try:
                done = await self.wait_until_deadline(
                    {claim_task, cancel_task}, deadline
                )
            except asyncio.CancelledError:
                failure = _cancelled(started=False)
                self._detach_setup(
                    pending,
                    lambda task: self._cleanup_late_claim(
                        task, _ledger_failure(failure)
                    ),
                )
                raise

            if claim_task not in done:
                failure = (
                    _cancelled(started=False)
                    if cancel_task in done or context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                self._detach_setup(
                    pending,
                    lambda task: self._cleanup_late_claim(
                        task, _ledger_failure(failure)
                    ),
                )
                return None, failure

            try:
                claim = claim_task.result()
            except IdempotencyCapacityExceeded as error:
                return None, _ToolExecutionFailure(
                    error=_PUBLIC_CAPACITY,
                    error_code="IDEMPOTENCY_CAPACITY_EXCEEDED",
                    retryable=True,
                    outcome="not_started",
                    cause=error,
                )
            except IdempotencyConflictError as error:
                return None, _ToolExecutionFailure(
                    error=_PUBLIC_CONFLICT,
                    error_code="IDEMPOTENCY_CONFLICT",
                    retryable=False,
                    outcome="not_started",
                    cause=error,
                )
            except (TypeError, ValueError) as error:
                return None, _ToolExecutionFailure(
                    error=_PUBLIC_INVALID_ARGUMENTS,
                    error_code="INVALID_TOOL_ARGUMENTS",
                    retryable=False,
                    outcome="not_started",
                    cause=error,
                )
            except Exception as error:
                return None, _ToolExecutionFailure(
                    error=_PUBLIC_EXECUTION_FAILURE,
                    error_code="TOOL_EXECUTION_FAILED",
                    retryable=True,
                    outcome="not_started",
                    cause=error,
                )
            finally:
                self._finish_setup(pending)

            if claim.kind != "owner":
                return claim, None
            if context.cancellation_token.is_cancelled or self._clock() >= deadline:
                failure = (
                    _cancelled(started=False)
                    if context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                cleanup = self._start_setup(
                    session_id=context.session_id,
                    call_id=context.tool_call_id,
                    operation=lambda: self.ledger.retryable_failure(
                        claim, _ledger_failure(failure)
                    ),
                )
                self._continue_setup(cleanup)
                return None, failure
            return claim, None
        finally:
            await _cancel_and_join(cancel_task)

    async def _cleanup_late_claim(
        self,
        claim_task: asyncio.Task[Any],
        failure: ToolIdempotencyFailure,
    ) -> None:
        try:
            claim = await claim_task
        except (
            asyncio.CancelledError,
            IdempotencyCapacityExceeded,
            IdempotencyConflictError,
        ):
            return
        except Exception as error:
            log_redacted_failure(
                logger, logging.ERROR, "Late tool idempotency claim failed", error
            )
            return
        if claim.kind == "owner":
            async with self._setup_semaphore:
                await self.ledger.retryable_failure(claim, failure)

    async def _is_started(
        self,
        claim: ToolIdempotencyClaim,
        session_id: str,
        call_id: str,
    ) -> bool:
        """Return False only after a bounded, successful persistence read."""
        pending = self._start_setup(
            session_id=session_id,
            call_id=call_id,
            operation=lambda: self.ledger.is_started(claim),
        )
        try:
            done = await self.wait_until_deadline(
                {pending.task},
                self._clock()
                + min(
                    _STARTED_LOOKUP_TIMEOUT_SECONDS,
                    self.limits.timeout_seconds,
                ),
            )
        except asyncio.CancelledError:
            self._detach_setup(pending, self._consume_late_setup)
            raise
        if pending.task not in done:
            self._detach_setup(pending, self._consume_late_setup)
            return True
        try:
            return bool(pending.task.result())
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Tool idempotency start-state lookup failed",
                error,
            )
            return True
        finally:
            self._finish_setup(pending)

    @staticmethod
    async def _consume_late_setup(task: asyncio.Task[Any]) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            log_redacted_failure(
                logger, logging.ERROR, "Late tool setup operation failed", error
            )

    async def _cleanup_late_mark(
        self,
        mark_task: asyncio.Task[Any],
        claim: ToolIdempotencyClaim,
        failure: ToolIdempotencyFailure,
    ) -> None:
        try:
            await mark_task
        except asyncio.CancelledError:
            pass
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Late tool idempotency start marker failed",
                error,
            )
        async with self._setup_semaphore:
            await self.ledger.unknown_outcome(claim, failure)

    async def execute(
        self,
        invocation: ToolInvocation,
        spec: ToolSpec,
        executor: ToolExecutor,
        emit_started: StartedEmitter,
    ) -> _ToolExecutionOutcome:
        """Measure one bounded execution without exposing tool inputs as telemetry."""
        started = self._clock()
        context = invocation.context
        span = start_span(
            self._trace,
            "kaji.tool",
            {
                "session.id": context.session_id,
                "turn.id": context.turn_id,
                "request.id": context.request_id,
                "trace.id": context.trace_id,
                "tool.call_id": context.tool_call_id,
            },
        )
        try:
            outcome = await self._execute_bounded(
                invocation,
                spec,
                executor,
                emit_started,
            )
        except asyncio.CancelledError as error:
            span_record_error(span, error)
            record_metric(
                self._metrics,
                "kaji.tool.duration_ms",
                (self._clock() - started) * 1_000,
                outcome="cancelled",
                error_code="TOOL_CANCELLED",
            )
            raise
        except BaseException as error:
            span_record_error(span, error)
            record_metric(
                self._metrics,
                "kaji.tool.duration_ms",
                (self._clock() - started) * 1_000,
                outcome="failed",
                error_code="OTHER",
            )
            raise
        else:
            failure = outcome.failure
            metric_outcome = "completed"
            error_code = "NONE"
            if failure is not None:
                if failure.cause is not None:
                    span_record_error(span, failure.cause)
                error_code = metric_error_code(failure.error_code)
                if failure.error_code == "TOOL_CANCELLED":
                    metric_outcome = "cancelled"
                elif failure.error_code in {"TOOL_TIMEOUT", "TURN_TIMEOUT"}:
                    metric_outcome = "timeout"
                else:
                    metric_outcome = failure.outcome
            record_metric(
                self._metrics,
                "kaji.tool.duration_ms",
                (self._clock() - started) * 1_000,
                outcome=metric_outcome,
                error_code=error_code,
            )
            return outcome
        finally:
            span_end(span)

    async def _execute_bounded(
        self,
        invocation: ToolInvocation,
        spec: ToolSpec,
        executor: ToolExecutor,
        emit_started: StartedEmitter,
    ) -> _ToolExecutionOutcome:
        """Execute or replay one preflighted invocation under runtime bounds."""
        context = invocation.context
        queue_started = self._clock()
        effective_deadline = self._effective_deadline(
            context.deadline_monotonic, spec.timeout_ms
        )
        deadline = effective_deadline.value
        claim, claim_failure = await self._claim_with_deadline(
            invocation, effective_deadline
        )
        if claim_failure is not None:
            return _ToolExecutionOutcome(failure=claim_failure)
        if claim is None:
            raise RuntimeError("tool idempotency claim returned no state")

        if claim.kind in ("completed", "unknown"):
            if claim.resolution is None:
                raise RuntimeError("idempotency replay is missing its resolution")
            return _from_resolution(claim.resolution)
        if claim.kind == "waiter":
            return await self._wait_for_owner(
                claim,
                context.cancellation_token,
                deadline,
                outer_timeout=effective_deadline.outer,
            )

        gate_acquired = False
        gate_accounted = False
        gate_task = asyncio.create_task(self._acquire_gate(spec.parallel_safe))
        gate_cancel_task = asyncio.create_task(context.cancellation_token.wait())
        try:
            done = await self.wait_until_deadline(
                {gate_task, gate_cancel_task}, deadline
            )
            if gate_task in done:
                gate_task.result()
                gate_acquired = True
            if not gate_acquired:
                gate_acquired = await _cancel_acquisition(gate_task)
                failure = (
                    _cancelled(started=False)
                    if gate_cancel_task in done
                    or context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                if gate_acquired:
                    await self._release_gate(spec.parallel_safe)
                    gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                return _ToolExecutionOutcome(failure=failure)
            if context.cancellation_token.is_cancelled or self._clock() >= deadline:
                failure = (
                    _cancelled(started=False)
                    if context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                return _ToolExecutionOutcome(failure=failure)
        except asyncio.CancelledError:
            if not gate_accounted:
                if not gate_acquired:
                    gate_acquired = await _cancel_acquisition(gate_task)
                if gate_acquired:
                    await self._release_gate(spec.parallel_safe)
                    gate_acquired = False
                gate_accounted = True
            failure = _cancelled(started=False)
            await self.ledger.retryable_failure(claim, _ledger_failure(failure))
            raise
        finally:
            await _cancel_and_join(gate_cancel_task)

        acquired = False
        permit_accounted = False
        handler_started = False
        claim_resolved = False
        acquire_task = asyncio.create_task(self._semaphore.acquire())
        cancel_task = asyncio.create_task(context.cancellation_token.wait())
        try:
            done = await self.wait_until_deadline({acquire_task, cancel_task}, deadline)
            if acquire_task in done:
                acquire_task.result()
                acquired = True
            if not acquired:
                acquired = await _cancel_acquisition(acquire_task)
                failure = (
                    _cancelled(started=False)
                    if cancel_task in done or context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                if acquired:
                    self._semaphore.release()
                    acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                record_metric(
                    self._metrics,
                    "kaji.tool.queue_wait_ms",
                    (self._clock() - queue_started) * 1_000,
                    outcome=(
                        "cancelled"
                        if failure.error_code == "TOOL_CANCELLED"
                        else "timeout"
                    ),
                )
                return _ToolExecutionOutcome(failure=failure)

            record_metric(
                self._metrics,
                "kaji.tool.queue_wait_ms",
                (self._clock() - queue_started) * 1_000,
                outcome="acquired",
            )

            if context.cancellation_token.is_cancelled:
                failure = _cancelled(started=False)
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)
            if self._clock() >= deadline:
                failure = _timed_out(started=False, outer=effective_deadline.outer)
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)

            from kaji.runtime.agents.cancellation import (  # noqa: PLC0415
                CancellationToken,
            )

            child_token = CancellationToken()
            child_context = replace(
                context,
                cancellation_token=child_token,
                deadline_monotonic=deadline,
                metadata=_copy_metadata_snapshot(context.metadata),
            )
            child_invocation = ToolInvocation(
                name=invocation.name,
                arguments=invocation.arguments,
                context=child_context,
            )

            async def record_started() -> None:
                await emit_started()

            # A Started append is an acknowledgement boundary, not detachable
            # setup work. Journal implementations must be cancellation-
            # cooperative so a terminal event cannot overtake a late Started.
            emit_task = asyncio.create_task(record_started())
            done = await self.wait_until_deadline({emit_task, cancel_task}, deadline)
            emit_error: BaseException | None = None
            if emit_task in done:
                try:
                    emit_task.result()
                except BaseException as error:
                    emit_error = error
            else:
                _, emit_error = await _cancel_operation(emit_task)

            if emit_error is not None:
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                failure = _ToolExecutionFailure(
                    error="Tool execution did not start",
                    error_code="TOOL_START_RECORD_FAILED",
                    retryable=True,
                    outcome="not_started",
                )
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                raise emit_error

            if context.cancellation_token.is_cancelled or self._clock() >= deadline:
                failure = (
                    _cancelled(started=False)
                    if context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)

            mark_pending = self._start_setup(
                session_id=context.session_id,
                call_id=context.tool_call_id,
                operation=lambda: self.ledger.mark_started(claim),
            )
            mark_task = mark_pending.task
            try:
                done = await self.wait_until_deadline(
                    {mark_task, cancel_task}, deadline
                )
            except asyncio.CancelledError:
                failure = _cancelled(started=True)
                self._detach_setup(
                    mark_pending,
                    lambda task: self._cleanup_late_mark(
                        task,
                        claim,
                        _ledger_failure(failure),
                    ),
                )
                claim_resolved = True
                raise

            if mark_task not in done:
                failure = (
                    _cancelled(started=True)
                    if cancel_task in done or context.cancellation_token.is_cancelled
                    else _timed_out(started=True, outer=effective_deadline.outer)
                )
                self._detach_setup(
                    mark_pending,
                    lambda task: self._cleanup_late_mark(
                        task,
                        claim,
                        _ledger_failure(failure),
                    ),
                )
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)

            mark_error: BaseException | None = None
            try:
                mark_task.result()
            except BaseException as error:
                mark_error = error
            finally:
                self._finish_setup(mark_pending)
            if mark_error is not None:
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                failure = _ToolExecutionFailure(
                    error=_PUBLIC_EXECUTION_FAILURE,
                    error_code="TOOL_EXECUTION_FAILED",
                    retryable=True,
                    outcome="not_started",
                    cause=mark_error,
                )
                cleanup = self._start_setup(
                    session_id=context.session_id,
                    call_id=context.tool_call_id,
                    operation=lambda: self.ledger.retryable_failure(
                        claim, _ledger_failure(failure)
                    ),
                )
                self._continue_setup(cleanup)
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)
            if context.cancellation_token.is_cancelled or self._clock() >= deadline:
                failure = (
                    _cancelled(started=False)
                    if context.cancellation_token.is_cancelled
                    else _timed_out(started=False, outer=effective_deadline.outer)
                )
                self._semaphore.release()
                acquired = False
                permit_accounted = True
                await self._release_gate(spec.parallel_safe)
                gate_acquired = False
                gate_accounted = True
                await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)

            async def invoke() -> Any:
                return await executor(child_invocation)

            task = asyncio.create_task(invoke())
            handler_started = True
            key = (context.session_id, context.tool_call_id)
            settlement: asyncio.Future[_Settlement] = (
                asyncio.get_running_loop().create_future()
            )
            watcher = asyncio.create_task(
                self._settle_execution(
                    key,
                    task,
                    spec.parallel_safe,
                    settlement,
                )
            )
            self._active[key] = _ActiveExecution(
                call_id=context.tool_call_id,
                task=watcher,
            )
            record_metric(self._metrics, "kaji.tool.active", len(self._active))
            acquired = False  # The settlement callback now owns the permit.
            permit_accounted = True
            gate_acquired = False  # The settlement callback now owns the gate.
            gate_accounted = True

            done = await self.wait_until_deadline({settlement, cancel_task}, deadline)
            if settlement in done:
                completed = settlement.result()
                if completed.cause is None:
                    try:
                        snapshot = durable_json_snapshot(
                            completed.result,
                            subject="tool_result",
                            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
                        )
                    except (InvalidDurableValueError, DurableJsonLimitError) as error:
                        failure = _invalid_tool_result(error)
                        await self.ledger.unknown_outcome(
                            claim, _durable_result_tombstone(error)
                        )
                        claim_resolved = True
                        return _ToolExecutionOutcome(failure=failure)
                    try:
                        await self.ledger.complete(claim, snapshot)
                    except Exception as error:
                        failure = _ToolExecutionFailure(
                            error=_PUBLIC_EXECUTION_FAILURE,
                            error_code="TOOL_EXECUTION_FAILED",
                            retryable=False,
                            outcome="unknown",
                            cause=error,
                        )
                        await self.ledger.unknown_outcome(
                            claim, _ledger_failure(failure)
                        )
                        claim_resolved = True
                        return _ToolExecutionOutcome(failure=failure)
                    claim_resolved = True
                    return _ToolExecutionOutcome(result=snapshot)
                if isinstance(completed.cause, ToolExecutionError):
                    recovery = _integration_recovery_fields(completed.cause)
                    failure = _ToolExecutionFailure(
                        error=_PUBLIC_EXECUTION_FAILURE,
                        error_code=completed.cause.error_code,
                        retryable=completed.cause.retryable,
                        outcome=completed.cause.outcome,
                        reason_code=recovery.get("reason_code"),
                        recovery_code=recovery.get("recovery_code"),
                        doc_url=recovery.get("doc_url"),
                        cause=completed.cause,
                    )
                    await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                else:
                    recovery = _integration_transport_failure_fields(completed.cause)
                    failure = _ToolExecutionFailure(
                        error=_PUBLIC_EXECUTION_FAILURE,
                        error_code=recovery.get("error_code", "TOOL_EXECUTION_FAILED"),
                        retryable=False,
                        outcome="unknown",
                        reason_code=recovery.get("reason_code"),
                        recovery_code=recovery.get("recovery_code"),
                        doc_url=recovery.get("doc_url"),
                        cause=completed.cause,
                    )
                    await self.ledger.unknown_outcome(claim, _ledger_failure(failure))
                claim_resolved = True
                return _ToolExecutionOutcome(failure=failure)

            if cancel_task in done or context.cancellation_token.is_cancelled:
                failure = _cancelled(started=True)
            else:
                failure = _timed_out(started=True, outer=effective_deadline.outer)
            child_token.cancel()
            task.cancel()
            await self.ledger.unknown_outcome(claim, _ledger_failure(failure))
            claim_resolved = True
            return _ToolExecutionOutcome(failure=failure)
        except asyncio.CancelledError:
            if "emit_task" in locals() and not emit_task.done():
                await _cancel_operation(emit_task)
            if (
                "mark_task" in locals()
                and not mark_task.done()
                and mark_pending.settlement is None
            ):
                await _cancel_operation(mark_task)
            if not permit_accounted:
                if not acquired:
                    acquired = await _cancel_acquisition(acquire_task)
                if acquired:
                    self._semaphore.release()
                    acquired = False
                permit_accounted = True
            if not gate_accounted:
                if gate_acquired:
                    await self._release_gate(spec.parallel_safe)
                    gate_acquired = False
                gate_accounted = True
            if handler_started and "task" in locals() and not task.done():
                child_token.cancel()
                task.cancel()
            if not claim_resolved:
                if handler_started:
                    failure = _cancelled(started=True)
                    await self.ledger.unknown_outcome(claim, _ledger_failure(failure))
                else:
                    failure = _cancelled(started=False)
                    await self.ledger.retryable_failure(claim, _ledger_failure(failure))
                claim_resolved = True
            raise
        finally:
            await _cancel_and_join(cancel_task)

    async def _wait_for_owner(
        self,
        claim: ToolIdempotencyClaim,
        cancellation_token: CancellationToken,
        deadline: float,
        *,
        outer_timeout: bool,
    ) -> _ToolExecutionOutcome:
        wait_task = asyncio.create_task(self.ledger.wait(claim))
        cancel_task = asyncio.create_task(cancellation_token.wait())
        try:
            done = await self.wait_until_deadline({wait_task, cancel_task}, deadline)
            if wait_task in done:
                return _from_resolution(wait_task.result())
            started = await self._is_started(
                claim,
                claim.session_id,
                claim.tool_call_id,
            )
            return _ToolExecutionOutcome(
                failure=(
                    _cancelled(started=started)
                    if cancel_task in done or cancellation_token.is_cancelled
                    else _timed_out(started=started, outer=outer_timeout)
                )
            )
        finally:
            await _cancel_and_join(wait_task)
            await _cancel_and_join(cancel_task)

    def _effective_deadline(
        self,
        turn_deadline: float | None,
        timeout_ms: int | None,
    ) -> _EffectiveDeadline:
        now = self._clock()
        local_deadlines = [now + self.limits.timeout_seconds]
        if timeout_ms is not None:
            local_deadlines.append(now + timeout_ms / 1000)
        local_deadline = min(local_deadlines)
        if turn_deadline is not None and turn_deadline <= local_deadline:
            return _EffectiveDeadline(turn_deadline, outer=True)
        return _EffectiveDeadline(local_deadline, outer=False)

    def approval_deadline(self, turn_deadline: float | None) -> _EffectiveDeadline:
        """Return the effective absolute approval deadline using this clock."""
        local_deadline = self._clock() + self.limits.approval_timeout_seconds
        if turn_deadline is not None and turn_deadline <= local_deadline:
            return _EffectiveDeadline(turn_deadline, outer=True)
        return _EffectiveDeadline(local_deadline, outer=False)

    async def wait_until_deadline(
        self,
        tasks: set[asyncio.Future[Any] | asyncio.Task[Any]],
        deadline: float,
    ) -> set[asyncio.Future[Any] | asyncio.Task[Any]]:
        """Wait for task settlement or an injected monotonic deadline."""
        loop = asyncio.get_running_loop()
        deadline_wait: asyncio.Future[None] = loop.create_future()
        timer = self._timer_scheduler.call_later(
            max(0.0, deadline - self._clock()),
            lambda: (
                deadline_wait.set_result(None) if not deadline_wait.done() else None
            ),
        )
        try:
            done, _ = await asyncio.wait(
                {*tasks, deadline_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            done.discard(deadline_wait)
            return done
        finally:
            timer.cancel()
            if not deadline_wait.done():
                deadline_wait.cancel()

    def start_approval(
        self,
        call_id: str,
        operation: Callable[[], Coroutine[Any, Any, Any]],
    ) -> asyncio.Task[Any] | None:
        """Own one bounded approval task until it physically settles."""
        if len(self._pending_approvals) >= self.limits.max_parallel:
            return None
        self._next_approval_id += 1
        operation_id = self._next_approval_id
        task = asyncio.create_task(operation())
        self._pending_approvals[operation_id] = _PendingApproval(
            operation_id=operation_id,
            call_id=call_id,
            task=task,
        )
        task.add_done_callback(
            lambda settled, owned_id=operation_id: self._approval_settled(
                owned_id,
                settled,
            )
        )
        return task

    def _approval_settled(
        self,
        operation_id: int,
        task: asyncio.Task[Any],
    ) -> None:
        self._pending_approvals.pop(operation_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except BaseException as error:
            log_no_throw(
                logger,
                logging.ERROR,
                "Detached approval handler failed (%s; details redacted)",
                type(error).__name__,
            )

    def deadline_expired(self, deadline: float) -> bool:
        """Compare an absolute deadline against the controller's injected clock."""
        return self._clock() >= deadline

    def deadline_remaining(self, deadline: float) -> float:
        """Return non-negative time remaining on an absolute deadline."""
        return max(0.0, deadline - self._clock())

    async def _acquire_gate(self, parallel_safe: bool) -> None:
        async with self._gate:
            if parallel_safe:
                await self._gate.wait_for(
                    lambda: not self._exclusive_active and self._exclusive_waiters == 0
                )
                self._safe_claims += 1
                return
            self._exclusive_waiters += 1
            try:
                await self._gate.wait_for(
                    lambda: not self._exclusive_active and self._safe_claims == 0
                )
                self._exclusive_active = True
            finally:
                self._exclusive_waiters -= 1
                self._gate.notify_all()

    async def _release_gate(self, parallel_safe: bool) -> None:
        async with self._gate:
            if parallel_safe:
                if self._safe_claims < 1:
                    raise RuntimeError("parallel tool gate released more than once")
                self._safe_claims -= 1
            else:
                if not self._exclusive_active:
                    raise RuntimeError("exclusive tool gate released more than once")
                self._exclusive_active = False
            self._gate.notify_all()

    async def _settle_execution(
        self,
        key: tuple[str, str],
        handler: asyncio.Task[Any],
        parallel_safe: bool,
        settlement: asyncio.Future[_Settlement],
    ) -> None:
        try:
            try:
                result = await handler
            except BaseException as error:
                outcome = _Settlement(cause=error)
            else:
                outcome = _Settlement(result=result)
            self._semaphore.release()
            await self._release_gate(parallel_safe)
            if not settlement.done():
                settlement.set_result(outcome)
        finally:
            self._active.pop(key, None)
            record_metric(self._metrics, "kaji.tool.active", len(self._active))

    async def drain_tools(self, timeout: float) -> list[str]:
        """Wait for executing handlers and durable setup to actually settle."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a non-negative number")
        if not math.isfinite(float(timeout)) or timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        deadline = self._clock() + float(timeout)
        while self._active or self._pending_setup or self._pending_approvals:
            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            tasks = [active.task for active in self._active.values()]
            tasks.extend(
                pending.settlement or pending.task
                for pending in self._pending_setup.values()
            )
            tasks.extend(pending.task for pending in self._pending_approvals.values())
            await self.wait_until_deadline(set(tasks), deadline)
            await asyncio.sleep(0)
        return sorted(
            [active.call_id for active in self._active.values()]
            + [pending.call_id for pending in self._pending_setup.values()]
            + [pending.call_id for pending in self._pending_approvals.values()]
        )
