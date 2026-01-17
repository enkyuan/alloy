"""
Taskiq Tasks for Hermes "Slow Path".

These tasks are executed by background workers when the LLM determines
a tool call is needed that takes time or side-effects (e.g. Spotify API).
"""

from typing import Any, Dict

from app.core.broker import broker, QUEUE_HIGH_PRIORITY, QUEUE_BACKGROUND
from app.services.spotify import spotify_service, spotify_client
from app.core.database import SessionLocal
from app.models.integration import Integration
from app.core.redis import get_redis_client, RedisKeys
from app.core.events import ToolResult
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
    
    try:
        if tool_name == "spotify_play":
            # Example implementation for Spotify
            result_data = await _handle_spotify_play(user_id, tool_args)
        elif tool_name == "spotify_pause":
             result_data = await _handle_spotify_pause(user_id)
        else:
            error_msg = f"Unknown tool: {tool_name}"

    except Exception as e:
        error_msg = str(e)

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

async def _handle_spotify_play(user_id: str, args: dict):
    """Helper to handle spotify play command."""
    db = SessionLocal()
    try:
        # Fetch integration and token (simplified)
        integration = db.query(Integration).filter_by(user_id=user_id, service="spotify").first()
        if not integration:
            raise ValueError("No Spotify integration found")
        
        token = await spotify_service.get_valid_token(integration, db)
        await spotify_service.search_and_play_track(args.get("query"), token)
        return {"status": "playing", "query": args.get("query")}
    finally:
        db.close()

async def _handle_spotify_pause(user_id: str):
    db = SessionLocal()
    try:
        integration = db.query(Integration).filter_by(user_id=user_id, service="spotify").first()
        if not integration:
            raise ValueError("No Spotify integration")
        
        token = await spotify_service.get_valid_token(integration, db)
        await spotify_service.pause_playback(token)
        return {"status": "paused"}
    finally:
        db.close()
