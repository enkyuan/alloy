import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

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
    validation_failure_fields,
)
from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
from kaji.runtime.tools.registry import ToolSpec
from kaji.runtime.tools.validation import ToolSchemaValidator

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]
ApprovalHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]


def _sanitize_error(exc: BaseException, *, max_len: int = 200) -> str:
    """Return a log-safe error string. Includes class name and a length-capped message.

    Handler exceptions can carry secrets (connection strings, tokens). The full
    exception is logged via ``logger.exception`` for operator visibility, but the
    event log only carries the truncated form.
    """
    msg = str(exc)
    if len(msg) > max_len:
        msg = msg[:max_len] + "…"
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


class ToolPlanner:
    """Scatter-gather executor for tool calls with policy and approval gating.

    Tool arguments are validated against ``ToolSpec.parameters`` before execution;
    schema mismatches emit ``TOOL_CALL_FAILED`` without invoking the handler.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        policy: Optional[ToolPolicy] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        specs: Optional[Dict[str, ToolSpec]] = None,
    ):
        self.executor = executor
        self.policy = policy
        self.approval_handler = approval_handler
        self._specs: Dict[str, ToolSpec] = specs or {}
        self._schema_validator = ToolSchemaValidator(self._specs)

    async def execute_scatter_gather(
        self,
        session_id: str,
        tool_calls: List[Dict[str, Any]],
        emit_event: Callable[[Any], Awaitable[None]],
    ) -> List[Dict[str, Any]]:
        """Execute multiple tools simultaneously and emit lifecycle events."""
        tasks = []
        for call in tool_calls:
            tasks.append(self._execute_single(session_id, call, emit_event))

        return list(await asyncio.gather(*tasks))

    async def _execute_single(
        self,
        session_id: str,
        call: Dict[str, Any],
        emit_event: Callable[[Any], Awaitable[None]],
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
        call_id = call.get("id", str(uuid.uuid4()))
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
                approved = await self.approval_handler(tool_name, tool_args, risk)

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
            result = await self.executor(tool_name, tool_args)

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

        except Exception as exc:
            logger.exception("Tool execution failed: %s", tool_name)
            error_msg = _sanitize_error(exc)

            # 6. Mark failure
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
