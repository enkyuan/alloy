"""
LLM response handling helpers for the LLM worker.
"""

import logging
import uuid
from typing import Any

from app.core.events import AgentResponse, ToolCall
from app.services.pipeline.helpers.function_calls import extract_response_function_calls

logger = logging.getLogger(__name__)


async def dispatch_tool_calls(
    redis: Any,
    user_id: str,
    function_calls: list[Any],
    *,
    execute_tool_call_task: Any,
    publish_user_update: Any,
) -> None:
    for function_call in function_calls:
        logger.info("LLM requested tool: %s", function_call.name)

        tool_call_id = str(uuid.uuid4())
        tool_args: dict[str, Any] = {}
        if function_call.args:
            for key, value in function_call.args.items():
                tool_args[str(key)] = value

        await execute_tool_call_task.kiq(
            user_id=user_id,
            tool_name=function_call.name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )

        tool_call_event = ToolCall(
            tool_name=function_call.name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )
        await publish_user_update(
            redis,
            event_type="tool.call",
            user_id=user_id,
            payload=tool_call_event,
            metadata={"source": "llm_worker.llm_function_call"},
        )


async def handle_llm_response(
    redis: Any,
    user_id: str,
    response: Any,
    *,
    execute_tool_call_task: Any,
    publish_user_update: Any,
    append_history: Any,
    history_limit: int,
) -> None:
    function_calls = extract_response_function_calls(response)

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
            publish_user_update=publish_user_update,
        )
        return

    response_text = response.text or ""
    if not response_text:
        logger.warning("Gemini returned an empty response")
        response_text = "Sorry, I couldn't generate a response right now."

    await append_history(
        redis,
        user_id,
        "assistant",
        response_text,
        history_limit=history_limit,
    )
    logger.debug("Publishing agent response", extra={"user_id": user_id})
    response_event = AgentResponse(content=response_text)
    await publish_user_update(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "llm_worker.llm_text_response"},
    )
    logger.info("Published agent response: %s...", response_text[:30])
