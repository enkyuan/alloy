import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from agentkit.infra.events.schemas import (
    ToolApprovalApproved,
    ToolApprovalRejected,
    ToolApprovalRequested,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
)
from agentkit.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
from agentkit.runtime.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]
# Approval handler: receives (tool_name, tool_args, risk) and returns True to approve.
ApprovalHandler = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]


class ToolPlanner:
    """Plans and executes tool calls concurrently (Scatter-Gather).

    Args:
        executor: An async callable ``(tool_name: str, args: dict) -> dict``
            that dispatches a single tool call. Typically wraps ``execute_tool``
            from the tool registry:

                ToolPlanner(
                    executor=lambda name, args: execute_tool("user-1", name, args)
                )

            For per-agent scoping with a ``ToolRegistry`` instance:

                ToolPlanner(
                    executor=lambda name, args: registry.execute("user-1", name, args)
                )

        policy: Optional ``ToolPolicy``. When provided, tools whose risk level
            is in ``policy.require_approval_for`` will pause for approval via
            ``approval_handler`` before execution.

        approval_handler: Async callback invoked when a tool requires approval.
            Receives ``(tool_name, tool_args, risk)`` and must return ``True``
            to allow execution or ``False`` to reject it. When omitted and a
            tool requires approval, it is rejected by default (fail-safe).

        specs: Optional mapping of tool name → ``ToolSpec`` used to look up
            the ``risk`` field per tool. When not provided, risk is treated as
            ``None`` (unclassified) for all tools.
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

        # 1. Announce intent to call
        await emit_event(
            ToolCallRequested(
                session_id=session_id,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=call_id,
            )
        )

        # 2. Allow/deny gate: policy violations fail before approval/execution.
        if self.policy is not None:
            try:
                self.policy.enforce(tool_name)
            except ToolPolicyViolation as error:
                error_msg = str(error)
                await emit_event(
                    ToolCallFailed(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        error=error_msg,
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
                await emit_event(
                    ToolApprovalRejected(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_call_id=call_id,
                        reason=reason,
                    )
                )
                return {
                    "id": call_id,
                    "name": tool_name,
                    "error": f"Tool approval rejected: {reason}",
                }

            await emit_event(
                ToolApprovalApproved(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                )
            )

        # 4. Mark execution as started
        await emit_event(
            ToolCallStarted(
                session_id=session_id, tool_name=tool_name, tool_call_id=call_id
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
                )
            )
            return {"id": call_id, "name": tool_name, "result": result}

        except Exception as e:
            error_msg = str(e)
            logger.error("Tool execution failed: %s", error_msg)

            # 6. Mark failure
            await emit_event(
                ToolCallFailed(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    error=error_msg,
                )
            )
            return {"id": call_id, "name": tool_name, "error": error_msg}
