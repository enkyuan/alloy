"""
Taskiq Tasks for Hermes "Slow Path".

These tasks are executed by background workers when the LLM determines
a tool call is needed that takes time or side-effects (e.g. Spotify API).
"""

from typing import Any, Dict

from app.core.broker import broker, QUEUE_HIGH_PRIORITY, QUEUE_BACKGROUND
from app.core.database import SessionLocal
from app.core.redis import get_redis_client, RedisKeys
from app.core.events import ToolResult
from app.services.integrations.dispatcher import execute_tool
import json

@broker.task(queue=QUEUE_HIGH_PRIORITY)
async def execute_tool_call(
    user_id: str,
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_call_id: str
) -> Dict[str, Any]:
    """
    Generic task to execute a tool call.
    Results are published back to Redis so the LLM Worker can resume.
    """
    result_data = None
    error_msg = None

    db = None
    try:
        db = SessionLocal()
        result_data = await execute_tool(user_id, tool_name, tool_args, db)
    except Exception as e:
        error_msg = str(e)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    # Publish result back to Redis
    # The LLM Worker (or a separate result processor) listens for this
    redis = await get_redis_client()
    
    tool_result = ToolResult(
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_data,
        error=error_msg,
        tool_call_id=tool_call_id
    )
    
    # We publish to a specific channel for the LLM worker or general updates
    # For simplicity in this prototype, we just publish to user updates channel
    # In a full system, we might stream this back to the specific reasoning loop
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps({
            "type": "tool.result",
            "user_id": user_id,
            "payload": tool_result.model_dump_json()
        })
    )
    
    return {"success": not error_msg, "tool_call_id": tool_call_id}

