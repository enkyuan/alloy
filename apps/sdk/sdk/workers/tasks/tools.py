"""
Taskiq Tasks for Agent "Slow Path".

These tasks are executed by background workers when the LLM determines
a tool call is needed that takes time or side-effects.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from sdk.core.broker import QUEUE_HIGH_PRIORITY, broker
from sdk.core.database import AsyncSessionLocal
from sdk.events.voice_models import ToolResult
from sdk.core.redis import get_redis_client
from sdk.providers.errors import ServiceNetworkError
from sdk.tools.registry import execute_tool
from sdk.workers.helpers.redis_events import (
    is_tool_call_retry_safe,
    clear_tool_call_execution_in_progress,
    claim_tool_call_execution,
    is_tool_call_execution_complete,
    mark_tool_call_execution_complete,
    publish_user_update,
)

logger = logging.getLogger(__name__)

TOOL_CALL_DEFAULT_TIMEOUT_SECONDS = 12.0
TOOL_CALL_MAX_ATTEMPTS = 3
TOOL_CALL_BASE_RETRY_DELAY_SECONDS = 0.5


def _extract_status_code(error: Exception) -> Optional[int]:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    response_status_code = getattr(response, "status_code", None)
    if isinstance(response_status_code, int):
        return response_status_code

    return None


def _tool_supports_retry(tool_name: str) -> bool:
    return is_tool_call_retry_safe(tool_name)


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, ServiceNetworkError):
        return True
    if isinstance(error, TimeoutError):
        return True

    status_code = _extract_status_code(error)
    if status_code is None:
        return False
    return status_code in {429, 500, 502, 503, 504}


@broker.task(queue=QUEUE_HIGH_PRIORITY)
async def execute_tool_call(
    user_id: str, tool_name: str, tool_args: Dict[str, Any], tool_call_id: str
) -> Dict[str, Any]:
    """
    Generic task to execute a tool call.
    Results are published back to Redis so the LLM Worker can resume.
    """
    result_data = None
    error_msg = None
    attempts = 0
    retryable = False
    last_error: Exception | None = None
    execution_marked_complete = False
    published = False

    logger.info(
        "Executing tool call %s for user %s (call_id: %s)",
        tool_name,
        user_id,
        tool_call_id,
    )

    redis = await get_redis_client()

    if await is_tool_call_execution_complete(redis, tool_call_id=tool_call_id):
        logger.info(
            "Skipping duplicate tool call because it was already completed",
            extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
        )
        return {"success": True, "tool_call_id": tool_call_id, "deduplicated": True}

    claimed = await claim_tool_call_execution(redis, tool_call_id=tool_call_id)
    if not claimed:
        logger.warning(
            "Skipping duplicate tool call because another worker is already processing it",
            extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
        )
        return {
            "success": False,
            "tool_call_id": tool_call_id,
            "deduplicated": True,
            "successfully_dispatched": False,
        }

    try:
        for attempts in range(1, TOOL_CALL_MAX_ATTEMPTS + 1):
            try:
                async with asyncio.timeout(TOOL_CALL_DEFAULT_TIMEOUT_SECONDS):
                    async with AsyncSessionLocal() as db:
                        result_data = await execute_tool(
                            user_id, tool_name, tool_args, db
                        )
                logger.info(
                    "Tool execution successful",
                    extra={
                        "tool_name": tool_name,
                        "user_id": user_id,
                        "attempts": attempts,
                    },
                )
                retryable = False
                last_error = None
                break
            except Exception as e:
                last_error = e
                is_retryable_error = _is_retryable_error(e)
                retryable = is_retryable_error and _tool_supports_retry(tool_name)
                if is_retryable_error and not _tool_supports_retry(tool_name):
                    logger.warning(
                        "Skipping tool retry because tool_name is marked non-idempotent",
                        extra={
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "attempt": attempts,
                        },
                    )
                if not retryable or attempts >= TOOL_CALL_MAX_ATTEMPTS:
                    logger.error(
                        "Tool execution failed",
                        extra={
                            "tool_name": tool_name,
                            "user_id": user_id,
                            "attempt": attempts,
                            "tool_call_id": tool_call_id,
                            "retryable": retryable,
                        },
                        exc_info=True,
                    )
                    error_msg = str(e)
                    break

                logger.warning(
                    "Retrying tool execution after transient error (%s/%s)",
                    attempts,
                    TOOL_CALL_MAX_ATTEMPTS,
                )
                delay = TOOL_CALL_BASE_RETRY_DELAY_SECONDS * (2 ** (attempts - 1))
                await asyncio.sleep(delay)

        tool_result = ToolResult(
            tool_name=tool_name,
            tool_args=tool_args,
            result=result_data,
            error=error_msg,
            tool_call_id=tool_call_id,
            user_id=user_id,
            metadata={
                "source": "taskiq.execute_tool_call",
                "attempts": attempts,
                "retryable_error": retryable,
                "error_type": type(last_error).__name__ if last_error else None,
            },
        )

        await mark_tool_call_execution_complete(
            redis, tool_call_id=tool_call_id
        )
        execution_marked_complete = True
        logger.info("Publishing tool result")
        try:
            await publish_user_update(
                redis,
                event_type="tool.result",
                user_id=user_id,
                payload=tool_result,
                metadata={"source": "taskiq.execute_tool_call"},
            )
            published = True
        except Exception as error:
            logger.warning(
                "Failed to publish tool result (outbox recovery may apply)",
                extra={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "user_id": user_id,
                    "error": str(error),
                },
                exc_info=True,
            )
        return {
            "success": not error_msg,
            "tool_call_id": tool_call_id,
            "published": published,
        }
    finally:
        if not execution_marked_complete:
            await clear_tool_call_execution_in_progress(
                redis,
                tool_call_id=tool_call_id,
            )
