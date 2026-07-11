import asyncio
import inspect
import logging
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
from kaji.runtime.tools.errors import (
    ToolArgumentValidationError,
    UnclassifiedToolRiskError,
    validation_failure_fields,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import (
    MissingToolIdentityError,
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.context import _copy_metadata_snapshot
from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
from kaji.runtime.tools.registry import ToolSpec, _snapshot_tool_spec
from kaji.runtime.tools.validation import ToolSchemaValidator

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[ToolInvocation], Awaitable[Any]]
LegacyToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]
ApprovalHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]

_legacy_executor_warned = False
_PUBLIC_TOOL_EXECUTION_FAILURE = "Tool execution failed"


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


class ToolPlanner:
    """Scatter-gather executor for tool calls with policy and approval gating.

    Tool arguments are validated against ``ToolSpec.parameters`` before execution;
    schema mismatches emit ``TOOL_CALL_FAILED`` without invoking the handler.
    """

    def __init__(
        self,
        executor: ToolExecutor | LegacyToolExecutor,
        *,
        policy: Optional[ToolPolicy] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        specs: Optional[Dict[str, ToolSpec]] = None,
    ):
        self.executor = _adapt_executor(executor)
        self.policy = policy
        self.approval_handler = approval_handler
        self._specs: Dict[str, ToolSpec] = {
            name: _snapshot_tool_spec(spec) for name, spec in (specs or {}).items()
        }
        self._schema_validator = ToolSchemaValidator(self._specs)

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
        """Execute multiple tools simultaneously after whole-batch preflight."""
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
        resolved_session_id = session_id
        resolved_turn_id = turn_id
        prepared_calls = self._prepare_calls(tool_calls)
        prepared = [
            (
                call,
                ToolExecutionContext(
                    principal_id=resolved_context.principal_id,
                    session_id=resolved_session_id,
                    turn_id=resolved_turn_id,
                    request_id=resolved_context.request_id,
                    trace_id=resolved_context.trace_id,
                    tool_call_id=call["id"],
                    idempotency_key=f"{resolved_session_id}:{call['id']}",
                    cancellation_token=cancellation_token,
                    deadline_monotonic=resolved_context.deadline_monotonic,
                    db=resolved_context.db,
                    metadata=_copy_metadata_snapshot(resolved_context.metadata),
                ),
            )
            for call in prepared_calls
        ]
        tasks = [
            self._execute_single(
                resolved_session_id,
                call,
                emit_event,
                execution_context=execution_context,
            )
            for call, execution_context in prepared
        ]
        return list(await asyncio.gather(*tasks))

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

    async def _execute_single(
        self,
        session_id: str,
        call: Dict[str, Any],
        emit_event: Callable[[Any], Awaitable[None]],
        *,
        execution_context: ToolExecutionContext,
    ) -> Dict[str, Any]:
        """Execute a single tool with policy enforcement and approval hooks."""
        tool_name = call.get("name", "unknown")
        raw_tool_args = call.get("arguments", {})
        validation_error: Optional[ToolArgumentValidationError] = None
        if not isinstance(raw_tool_args, dict):
            tool_args = {"__parse_error": "invalid arguments"}
            validation_error = ToolArgumentValidationError.non_object(tool_name)
        elif isinstance(raw_tool_args.get("__parse_error"), str):
            # Provider parse errors may contain fragments of the model output.
            # Keep only a stable sentinel in the event stream.
            tool_args = {"__parse_error": "invalid JSON"}
            validation_error = ToolArgumentValidationError.parse_error(tool_name)
        else:
            tool_args = raw_tool_args
        call_id = execution_context.tool_call_id
        spec = self._specs.get(tool_name)
        risk = spec.risk if spec else None
        catalog_name = spec.catalog_name if spec else None
        aliases = [catalog_name] if catalog_name else []
        # `Any` widens the dict to satisfy the type checker's parameter
        # type on the event constructors.
        metadata: Any = {"catalog_name": catalog_name} if catalog_name else {}

        # 1. Announce intent to call
        await emit_event(
            ToolCallRequested(
                session_id=session_id,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=call_id,
                metadata=metadata,
            )
        )

        # 2. Fail closed on provider parse errors and complete schema violations.
        if validation_error is None:
            try:
                self._schema_validator.validate(tool_name, tool_args)
            except ToolArgumentValidationError as error:
                validation_error = error
        if validation_error is not None:
            failure_fields = validation_failure_fields(validation_error)
            await emit_event(
                ToolCallFailed(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    error=validation_error.message,
                    metadata=metadata,
                    **failure_fields,
                )
            )
            return {
                "id": call_id,
                "name": tool_name,
                "error": validation_error.message,
                **failure_fields,
            }

        # 3. Allow/deny gate: policy violations fail before approval/execution.
        if self.policy is not None:
            try:
                self.policy.enforce_any(tool_name, aliases)
            except ToolPolicyViolation as error:
                error_msg = str(error)
                await emit_event(
                    ToolCallFailed(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        error=error_msg,
                        metadata=metadata,
                    )
                )
                return {"id": call_id, "name": tool_name, "error": error_msg}

        # 3. Approval gate: if policy requires it, pause and ask.
        if self.policy is not None and self.policy.requires_approval(tool_name, risk):
            await emit_event(
                ToolApprovalRequested(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    tool_args=tool_args,
                    risk=risk,
                    metadata=metadata,
                )
            )

            approved = False
            if self.approval_handler is not None:
                try:
                    approved = await self.approval_handler(tool_name, tool_args, risk)
                except Exception:
                    logger.exception("Tool approval handler failed: %s", tool_name)
                    reason = "Approval handler unavailable"
                    error_msg = "Tool approval unavailable"
                    await emit_event(
                        ToolApprovalRejected(
                            session_id=session_id,
                            tool_name=tool_name,
                            tool_call_id=call_id,
                            reason=reason,
                            metadata=metadata,
                        )
                    )
                    await emit_event(
                        ToolCallFailed(
                            session_id=session_id,
                            tool_name=tool_name,
                            tool_call_id=call_id,
                            error=error_msg,
                            error_code="APPROVAL_UNAVAILABLE",
                            retryable=False,
                            outcome="not_started",
                            metadata=metadata,
                        )
                    )
                    return {
                        "id": call_id,
                        "name": tool_name,
                        "error": error_msg,
                        "error_code": "APPROVAL_UNAVAILABLE",
                        "retryable": False,
                        "outcome": "not_started",
                    }

            if not approved:
                reason = (
                    "No approval handler registered"
                    if self.approval_handler is None
                    else "Rejected by approval handler"
                )
                error_msg = f"Tool approval rejected: {reason}"
                await emit_event(
                    ToolApprovalRejected(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        reason=reason,
                        metadata=metadata,
                    )
                )
                # Also emit ToolCallFailed so replay projects this into
                # model-visible history. Without it, the next iteration sees no
                # tool result and re-requests the same tool until max_iterations.
                await emit_event(
                    ToolCallFailed(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        error=error_msg,
                        metadata=metadata,
                    )
                )
                return {
                    "id": call_id,
                    "name": tool_name,
                    "error": error_msg,
                }

            await emit_event(
                ToolApprovalApproved(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    metadata=metadata,
                )
            )

        # 4. Mark execution as started
        await emit_event(
            ToolCallStarted(
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=call_id,
                metadata=metadata,
            )
        )

        try:
            # 5. Call the actual implementation
            result = await self.executor(
                ToolInvocation(
                    name=tool_name,
                    arguments=tool_args,
                    context=execution_context,
                )
            )

            # 6. Mark success
            await emit_event(
                ToolCallCompleted(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    result=result,
                    metadata=metadata,
                )
            )
            return {"id": call_id, "name": tool_name, "result": result}

        except Exception:
            logger.exception("Tool execution failed: %s", tool_name)

            # 6. Mark failure
            await emit_event(
                ToolCallFailed(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    error=_PUBLIC_TOOL_EXECUTION_FAILURE,
                    error_code="TOOL_EXECUTION_FAILED",
                    retryable=False,
                    outcome="failed",
                    metadata=metadata,
                )
            )
            return {
                "id": call_id,
                "name": tool_name,
                "error": _PUBLIC_TOOL_EXECUTION_FAILURE,
                "error_code": "TOOL_EXECUTION_FAILED",
                "retryable": False,
                "outcome": "failed",
            }
