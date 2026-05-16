import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List

from sdk.events.schemas import (
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
)

logger = logging.getLogger(__name__)

ToolExecutor = Callable[[str, Dict[str, Any]], Awaitable[Any]]


class ToolPlanner:
    """Plans and executes tool calls concurrently (Scatter-Gather)."""

    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    async def execute_scatter_gather(
        self,
        session_id: str,
        tool_calls: List[Dict[str, Any]],
        emit_event: Callable[[Any], Awaitable[None]],
    ) -> List[Dict[str, Any]]:
        """Executes multiple tools simultaneously and emits standard AgentKit lifecycle events."""
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
        """Executes a single tool safely wrapped in events."""
        tool_name = call.get("name", "unknown")
        tool_args = call.get("arguments", {})
        call_id = call.get("id", str(uuid.uuid4()))

        # 1. Announce intent to call
        await emit_event(
            ToolCallRequested(
                session_id=session_id,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=call_id,
            )
        )

        # 2. Mark execution as started
        await emit_event(
            ToolCallStarted(
                session_id=session_id, tool_name=tool_name, tool_call_id=call_id
            )
        )

        try:
            # 3. Call the actual implementation (via the adapter/executor)
            result = await self.executor(tool_name, tool_args)

            # 4. Mark success
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

            # 4. Mark failure
            await emit_event(
                ToolCallFailed(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_call_id=call_id,
                    error=error_msg,
                )
            )
            return {"id": call_id, "name": tool_name, "error": error_msg}
