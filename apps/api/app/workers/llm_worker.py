"""
LLM Worker - The "Reasoning Node" of the Hermes architecture.

This worker acts as the central brain:
1. Consumes 'user.transcription' events from Redis Stream `stream:voice_input`.
2. Reconstructs conversation context (fetching recent messages from DB).
3. Calls LLM (Gemini) with tool definitions.
4. If Tool Call: Dispatches to Taskiq `execute_tool_call` task.
5. If Text: Pushes 'agent.response' events to Redis.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.redis import get_redis_client, RedisKeys
from app.core.events import UserTranscriptionReceived, AgentResponse, ToolCall
from app.services.pipeline.gemini import get_gemini_service
from app.services.pipeline.tasks import execute_tool_call

logger = logging.getLogger(__name__)

# Define available tools (schema for Gemini)
TOOLS = [
    {
        "function_declarations": [
            {
                "name": "spotify_play",
                "description": "Play a song, artist, or album on Spotify.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "The song, artist, or album name to play."
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "spotify_pause",
                "description": "Pause Spotify playback.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                }
            }
        ]
    }
]

async def process_voice_input_stream():
    """Main loop for consuming voice input events."""
    redis = await get_redis_client()
    
    # Create consumer group if not exists
    try:
        await redis.xgroup_create(
            RedisKeys.STREAM_VOICE_INPUT,
            RedisKeys.GROUP_LLM_WORKER,
            id="0",
            mkstream=True
        )
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            logger.error(f"Error creating consumer group: {e}")

    logger.info(f"LLM Worker started listening on {RedisKeys.STREAM_VOICE_INPUT}")

    while True:
        try:
            # Read from stream using consumer group
            streams = await redis.xreadgroup(
                groupname=RedisKeys.GROUP_LLM_WORKER,
                consumername="llm_worker_1",
                streams={RedisKeys.STREAM_VOICE_INPUT: ">"},
                count=1,
                block=2000 
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for message_id, data in messages:
                    try:
                        await handle_message(data)
                        # Acknowledge message
                        await redis.xack(RedisKeys.STREAM_VOICE_INPUT, RedisKeys.GROUP_LLM_WORKER, message_id)
                    except Exception as e:
                        logger.error(f"Error processing message {message_id}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in LLM worker loop: {e}")
            await asyncio.sleep(1)

async def handle_message(data: dict):
    """Business logic for handling a single voice event."""
    event_type = data.get("type")
    
    if event_type != "user.transcription":
        return

    payload_json = data.get("payload")
    user_id = data.get("user_id")
    
    if not payload_json or not user_id:
        logger.warning("Received invalid message payload or missing user_id")
        return

    # Deserialize event
    transcription = UserTranscriptionReceived.model_validate_json(payload_json)
    
    logger.info(f"Processing transcription for user {user_id}: {transcription.content}")

    # Call LLM (Gemini) with Tools
    try:
        gemini = get_gemini_service()
        response = await gemini.generate_chat_response(
            messages=[{"role": "user", "content": transcription.content}],
            system_instruction="You are a helpful voice assistant. Use tools to control Spotify.",
            tools=TOOLS
        )
        
        # Check for function calls
        # Note: This parsing depends on the exact structure of the google-genai response object
        # which can be complex. We'll support the 'function_calls' attribute if present.
        
        function_calls = []
        if hasattr(response, "candidates") and response.candidates:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)

        redis = await get_redis_client()

        if function_calls:
            for fc in function_calls:
                logger.info(f"LLM requested tool: {fc.name}")
                
                # Dispatch to Taskiq (Slow Path)
                tool_call_id = str(uuid.uuid4())
                
                # Convert args to dict
                tool_args = {}
                if fc.args:
                    for key, value in fc.args.items():
                        tool_args[key] = value

                await execute_tool_call.kiq(
                    user_id=user_id,
                    tool_name=fc.name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id
                )
                
                # Publish ToolCall event to UI
                tc_event = ToolCall(tool_name=fc.name, tool_args=tool_args, tool_call_id=tool_call_id)
                await redis.publish(
                    RedisKeys.CHANNEL_USER_UPDATES,
                    json.dumps({
                        "type": "tool.call",
                        "user_id": user_id,
                        "payload": tc_event.model_dump_json()
                    })
                )
        
        else:
            # Normal text response
            response_text = response.text or ""
            response_event = AgentResponse(content=response_text)
            
            await redis.publish(
                RedisKeys.CHANNEL_USER_UPDATES,
                json.dumps({
                    "type": "agent.response",
                    "user_id": user_id,
                    "payload": response_event.model_dump_json()
                })
            )
            logger.info(f"Published agent response: {response_text[:30]}...")

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}", exc_info=True)

if __name__ == "__main__":
    from app.core.config import settings
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(process_voice_input_stream())
