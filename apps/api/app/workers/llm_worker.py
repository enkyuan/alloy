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
import hashlib
import json
import logging
import uuid

import app.services.integrations.tools  # ensure tool registration
from app.core.config import settings
from app.core.events import (
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
)
from app.core.redis import RedisKeys, get_redis_client
from app.services.integrations import list_tool_specs
from app.services.pipeline.gemini import get_gemini_service
from app.services.pipeline.tasks import execute_tool_call

logger = logging.getLogger(__name__)

HISTORY_LIMIT = settings.HERMES_HISTORY_LIMIT
CACHE_TTL_SECONDS = settings.HERMES_CACHE_TTL_SECONDS

SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. "
    "Use tools to control integrations when needed. "
    "If a tool result is provided, respond succinctly to the user."
)


def _history_key(user_id: str) -> str:
    return f"hermes:history:{user_id}"


def _response_cache_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"hermes:cache:{digest}"


def _cache_hit_key() -> str:
    return "hermes:cache:hit"


def _cache_miss_key() -> str:
    return "hermes:cache:miss"


def _tools_fingerprint() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in list_tool_specs()
    ]


async def _append_history(redis, user_id: str, role: str, content: str) -> None:
    entry = {"role": role, "content": content}
    await redis.rpush(_history_key(user_id), json.dumps(entry))
    if HISTORY_LIMIT and HISTORY_LIMIT > 0:
        await redis.ltrim(_history_key(user_id), -HISTORY_LIMIT, -1)


async def _get_history(redis, user_id: str) -> list[dict[str, str]]:
    raw_items = await redis.lrange(_history_key(user_id), 0, -1)
    messages: list[dict[str, str]] = []
    for item in raw_items:
        try:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            data = json.loads(item)
            if isinstance(data, dict) and "role" in data and "content" in data:
                messages.append(
                    {"role": str(data["role"]), "content": str(data["content"])}
                )
        except Exception:
            continue
    return messages


async def _dispatch_tool_calls(redis, user_id: str, function_calls) -> None:
    for fc in function_calls:
        logger.info(f"LLM requested tool: {fc.name}")

        tool_call_id = str(uuid.uuid4())
        tool_args = {}
        if fc.args:
            for key, value in fc.args.items():
                tool_args[key] = value

        await execute_tool_call.kiq(
            user_id=user_id,
            tool_name=fc.name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )

        tc_event = ToolCall(
            tool_name=fc.name, tool_args=tool_args, tool_call_id=tool_call_id
        )
        await redis.publish(
            RedisKeys.CHANNEL_USER_UPDATES,
            json.dumps(
                {
                    "type": "tool.call",
                    "user_id": user_id,
                    "payload": tc_event.model_dump_json(),
                }
            ),
        )


async def _handle_llm_response(redis, user_id: str, response) -> None:
    function_calls = []
    if hasattr(response, "candidates") and response.candidates:
        candidate = response.candidates[0]
        if (
            hasattr(candidate, "content")
            and candidate.content
            and hasattr(candidate.content, "parts")
            and candidate.content.parts
        ):
            for part in candidate.content.parts:
                if part.function_call:
                    function_calls.append(part.function_call)

    if function_calls:
        await _dispatch_tool_calls(redis, user_id, function_calls)
        return

    response_text = response.text or ""
    if not response_text:
        logger.warning("Gemini returned an empty response")
        # Don't send "Sorry" here if it was just a transient overload or empty safety block
        # just logging warning is often enough, or we can send a fallback.
        # But if we crashed before, we definitely sent nothing.
        # Let's send a fallback only if we really got nothing.
        if not function_calls:
            response_text = "Sorry, I couldn't generate a response right now."

    await _append_history(redis, user_id, "assistant", response_text)
    response_event = AgentResponse(content=response_text)
    await redis.publish(
        RedisKeys.CHANNEL_USER_UPDATES,
        json.dumps(
            {
                "type": "agent.response",
                "user_id": user_id,
                "payload": response_event.model_dump_json(),
            }
        ),
    )
    logger.info(f"Published agent response: {response_text[:30]}...")


def _build_tools_payload():
    declarations = []
    for spec in list_tool_specs():
        declarations.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
        )
    return [{"function_declarations": declarations}] if declarations else []


# Define available tools (schema for Gemini)
TOOLS = _build_tools_payload()


async def process_voice_input_stream():
    """Main loop for consuming voice input events."""
    redis = await get_redis_client()

    # Create consumer group if not exists
    try:
        await redis.xgroup_create(
            RedisKeys.STREAM_VOICE_INPUT,
            RedisKeys.GROUP_LLM_WORKER,
            id="0",
            mkstream=True,
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
                block=2000,
            )

            if not streams:
                continue

            for stream_name, messages in streams:
                for message_id, data in messages:
                    try:
                        await handle_message(data)
                        # Acknowledge message
                        await redis.xack(
                            RedisKeys.STREAM_VOICE_INPUT,
                            RedisKeys.GROUP_LLM_WORKER,
                            message_id,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error processing message {message_id}: {e}", exc_info=True
                        )

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
        redis = await get_redis_client()
        await _append_history(redis, user_id, "user", transcription.content)
        history = await _get_history(redis, user_id)
        cache_payload = {
            "messages": history,
            "system": SYSTEM_INSTRUCTION,
            "tools": _tools_fingerprint(),
        }
        cached_response = await redis.get(_response_cache_key(cache_payload))
        if cached_response:
            await redis.incr(_cache_hit_key())
            if isinstance(cached_response, bytes):
                cached_response = cached_response.decode("utf-8")
            response_event = AgentResponse(content=str(cached_response))
            await redis.publish(
                RedisKeys.CHANNEL_USER_UPDATES,
                json.dumps(
                    {
                        "type": "agent.response",
                        "user_id": user_id,
                        "payload": response_event.model_dump_json(),
                    }
                ),
            )
            await _append_history(redis, user_id, "assistant", str(cached_response))
            return
        await redis.incr(_cache_miss_key())
        response = await gemini.generate_chat_response(
            messages=history, system_instruction=SYSTEM_INSTRUCTION, tools=TOOLS
        )
        await _handle_llm_response(redis, user_id, response)
        if response.text:
            await redis.setex(
                _response_cache_key(cache_payload),
                CACHE_TTL_SECONDS,
                response.text,
            )

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}", exc_info=True)
        if user_id:
            redis = await get_redis_client()
            response_event = AgentResponse(
                content="Sorry, I ran into an error while generating a response."
            )
            await redis.publish(
                RedisKeys.CHANNEL_USER_UPDATES,
                json.dumps(
                    {
                        "type": "agent.response",
                        "user_id": user_id,
                        "payload": response_event.model_dump_json(),
                    }
                ),
            )


async def process_tool_results():
    """Listen for tool results and continue the Hermes loop."""
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(RedisKeys.CHANNEL_USER_UPDATES)
    logger.info("LLM Worker listening for tool results")
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0)
                continue

            raw = message.get("data")
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if event.get("type") != "tool.result":
                continue

            payload = event.get("payload")
            user_id = event.get("user_id")
            if not payload or not user_id:
                continue

            try:
                tool_result = ToolResult.model_validate_json(payload)
            except Exception:
                continue

            user_id = str(user_id)
            summary = tool_result.result_str or tool_result.error or ""
            if not summary:
                continue

            await _append_history(
                redis,
                user_id,
                "assistant",
                f"Tool result for {tool_result.tool_name}: {summary}",
            )
            history = await _get_history(redis, user_id)
            gemini = get_gemini_service()
            try:
                response = await gemini.generate_chat_response(
                    messages=history,
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=TOOLS,
                )
                await _handle_llm_response(redis, user_id, response)
                if response.text:
                    cache_payload = {
                        "messages": history,
                        "system": SYSTEM_INSTRUCTION,
                        "tools": _tools_fingerprint(),
                    }
                    await redis.setex(
                        _response_cache_key(cache_payload),
                        CACHE_TTL_SECONDS,
                        response.text,
                    )
            except Exception as e:
                logger.error(
                    f"LLM Generation failed after tool result: {e}", exc_info=True
                )
                response_event = AgentResponse(
                    content="Sorry, I ran into an error while generating a response."
                )
                await redis.publish(
                    RedisKeys.CHANNEL_USER_UPDATES,
                    json.dumps(
                        {
                            "type": "agent.response",
                            "user_id": user_id,
                            "payload": response_event.model_dump_json(),
                        }
                    ),
                )
    finally:
        await pubsub.unsubscribe(RedisKeys.CHANNEL_USER_UPDATES)
        await pubsub.close()


if __name__ == "__main__":
    from app.core.config import settings

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    async def _run():
        await asyncio.gather(
            process_voice_input_stream(),
            process_tool_results(),
        )

    asyncio.run(_run())
