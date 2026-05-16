"""
LLM response handling helpers for the LLM worker.
"""

import logging
import uuid
from typing import Any

from sdk.events.voice_models import AgentResponse, ToolCall
from sdk.workers.helpers.redis_events import publish_user_update_safely

logger = logging.getLogger(__name__)


async def dispatch_tool_calls(
    redis: Any,
    user_id: str,
    function_calls: list[Any],
    *,
    execute_tool_call_task: Any,
) -> None:
    for function_call in function_calls:
        # Generic response provides dictionaries with name and arguments
        tool_name = (
            function_call.get("name", "")
            if isinstance(function_call, dict)
            else getattr(function_call, "name", "")
        )
        logger.info("LLM requested tool: %s", tool_name)

        tool_call_id = (
            function_call.get("id", str(uuid.uuid4()))
            if isinstance(function_call, dict)
            else str(uuid.uuid4())
        )
        tool_args: dict[str, Any] = (
            function_call.get("arguments", {})
            if isinstance(function_call, dict)
            else dict(getattr(function_call, "args", {}))
        )

        await execute_tool_call_task.kiq(
            user_id=user_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )

        tool_call_event = ToolCall(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )
        await publish_user_update_safely(
            redis,
            event_type="tool.call",
            user_id=user_id,
            payload=tool_call_event,
            metadata={"source": "agent.llm_function_call"},
        )


async def handle_llm_response(
    redis: Any,
    user_id: str,
    response: Any,
    *,
    execute_tool_call_task: Any,
    append_history: Any,
    history_limit: int,
) -> str | None:
    # Use generic generic response structure
    function_calls = getattr(response, "tool_calls", [])

    if function_calls:
        logger.info(
            "LLM returned tool calls",
            extra={"user_id": user_id, "count": len(function_calls)},
        )
        await dispatch_tool_calls(
            redis,
            user_id,
            function_calls,
            execute_tool_call_task=execute_tool_call_task,
        )
        return None

    try:
        response_text = (
            str(response.text) if hasattr(response, "text") and response.text else ""
        )
    except ValueError:
        response_text = ""

    if not response_text:
        logger.warning("LLM returned an empty response")
        response_text = "Sorry, I couldn't generate a response right now."

    try:
        await append_history(
            redis,
            user_id,
            "assistant",
            response_text,
            history_limit=history_limit,
        )
    except Exception as error:
        logger.warning(
            "Failed to append LLM text response to history",
            extra={"user_id": user_id, "error": str(error)},
            exc_info=True,
        )
    logger.debug("Publishing agent response", extra={"user_id": user_id})
    response_event = AgentResponse(content=response_text)
    await publish_user_update_safely(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "agent.llm_text_response"},
    )
    logger.info("Published agent response: %s...", response_text[:30])
    return response_text
