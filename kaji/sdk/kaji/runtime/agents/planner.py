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
from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
from kaji.runtime.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]
ApprovalHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]

_JSON_TYPE_TO_PY: Dict[str, tuple] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _validate_args(spec: ToolSpec, args: Dict[str, Any]) -> Optional[str]:
    """Shallow JSON Schema check against ToolSpec.parameters. Returns error string or None.

    Checks: top-level ``type: object``, ``required`` keys present, and top-level
    property types. Deep schema features (anyOf, format, nested validation) are
    intentionally not enforced — the goal is to fail closed on shape mismatch
    from the model, not to be a general validator.
    """
    schema = spec.parameters or {}
    if schema.get("type") == "object" and not isinstance(args, dict):
        return f"arguments must be an object, got {type(args).__name__}"
    if not isinstance(args, dict):
        return None
    for key in schema.get("required", []) or []:
        if key not in args:
            return f"missing required argument: {key!r}"
    for key, prop_schema in (schema.get("properties") or {}).items():
        if key not in args:
            continue
        expected = prop_schema.get("type") if isinstance(prop_schema, dict) else None
        if not expected:
            continue
        py_types = _JSON_TYPE_TO_PY.get(expected)
        if py_types and not isinstance(args[key], py_types):
            return (
                f"argument {key!r}: expected {expected}, got {type(args[key]).__name__}"
            )
    return None


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
        tool_args = call.get("arguments", {})
        call_id = call.get("id", str(uuid.uuid4()))
        spec = self._specs.get(tool_name)
        risk = spec.risk if spec else None
        catalog_name = spec.catalog_name if spec else None
        aliases = [catalog_name] if catalog_name else []
        # `Any` widens the dict to satisfy pyrefly's `Mapping[LaxStr, Any]`
        # parameter type on the event constructors.
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

        # 2a. Provider parse-error sentinel: model produced unparseable tool JSON.
        if isinstance(tool_args, dict) and isinstance(
            tool_args.get("__parse_error"), str
        ):
            error_msg = f"Invalid tool arguments: {tool_args['__parse_error']}"
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

        # 2b. Schema validation: fail closed on malformed args from the model.
        if spec is not None:
            schema_error = _validate_args(spec, tool_args)
            if schema_error is not None:
                error_msg = f"Invalid tool arguments: {schema_error}"
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
