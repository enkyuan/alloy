"""
LLM Worker - The "Reasoning Node" of the agent pipeline.

This worker acts as the central process that consumes user transcriptions:
1. Consumes 'user.transcription' events from Redis Stream `stream:voice_input`.
2. Reconstructs conversation context (fetching recent messages from DB).
3. Calls LLM (Gemini) with tool definitions.
4. If Tool Call: Dispatches to Taskiq `execute_tool_call` task.
5. If Text: Pushes 'agent.response' events to Redis.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.events import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
    is_supported_event_version,
    parse_event_envelope,
)
from app.core.redis import RedisKeys, get_redis_client
from app.services.integrations.dispatcher import execute_tool
from app.services.parser import command_parser
from app.services.pipeline.routers.router import pipeline_router
from app.services.pipeline.services.gemini_service import get_gemini_service
from app.services.pipeline.helpers.tool_tasks import execute_tool_call
from app.workers.helpers.cache_keys import (
    cache_hit_key as _cache_hit_key,
    cache_miss_key as _cache_miss_key,
    response_cache_key as _response_cache_key,
)
from app.workers.helpers.intent_mapping import (
    map_intent_to_tool_call as _map_intent_to_tool_call,
)
from app.workers.helpers.llm_response import (
    handle_llm_response as _handle_llm_response,
)
from app.workers.helpers.redis_events import (
    append_history as _append_history,
    cache_spotify_result as _cache_spotify_result,
    get_history as _get_history,
    publish_user_update as _publish_user_update,
    try_cached_spotify_play as _try_cached_spotify_play,
)
from app.workers.helpers.response_text import format_response_text
from app.workers.helpers.tools_payload import (
    build_tools_payload as _build_tools_payload,
    tools_fingerprint as _tools_fingerprint,
)

logger = logging.getLogger(__name__)

# Normalize optional config to concrete ints for downstream helpers.
HISTORY_LIMIT: int = settings.AGENT_HISTORY_LIMIT or 0
CACHE_TTL_SECONDS = settings.AGENT_CACHE_TTL_SECONDS
SPOTIFY_CACHE_TTL_SECONDS = 60 * 60

SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. "
    "Use tools to control integrations when needed. "
    "If a tool result is provided, respond succinctly to the user."
)


def _is_quota_error(error: Exception) -> bool:
    message = str(error).lower()
    quota_markers = [
        "resource_exhausted",
        "quota",
        "rate limit",
        "rate_limit",
        "429",
    ]
    return any(marker in message for marker in quota_markers)


async def _execute_tool_fast(
    redis: Any, user_id: str, tool_name: str, tool_args: dict
) -> None:
    tool_call_id = str(uuid.uuid4())
    logger.info(
        "Fast-path tool execution",
        extra={
            "user_id": user_id,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
        },
    )

    tc_event = ToolCall(
        tool_name=tool_name, tool_args=tool_args, tool_call_id=tool_call_id
    )
    await _publish_user_update(
        redis,
        event_type="tool.call",
        user_id=user_id,
        payload=tc_event,
        metadata={"source": "llm_worker.fast_path"},
    )

    result_data = None
    error_msg = None
    db = None
    try:
        db = SessionLocal()
        result_data = await execute_tool(user_id, tool_name, tool_args, db)
    except Exception as e:
        logger.error(f"Fast-path tool failed: {e}", exc_info=True)
        error_msg = str(e)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    tool_result = ToolResult(
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_data,
        error=error_msg,
        tool_call_id=tool_call_id,
        user_id=user_id,
        metadata={"fast_path": True},
    )

    await _publish_user_update(
        redis,
        event_type="tool.result",
        user_id=user_id,
        payload=tool_result,
        metadata={"source": "llm_worker.fast_path"},
    )

    await _cache_spotify_result(
        redis,
        tool_result,
        spotify_cache_ttl_seconds=SPOTIFY_CACHE_TTL_SECONDS,
    )

    response_text = format_response_text(tool_result)
    if response_text:
        await _append_history(
            redis,
            user_id,
            "assistant",
            response_text,
            history_limit=HISTORY_LIMIT,
        )
        response_event = AgentResponse(content=response_text)
        await _publish_user_update(
            redis,
            event_type="agent.response",
            user_id=user_id,
            payload=response_event,
            metadata={"source": "llm_worker.fast_path"},
        )


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
    try:
        envelope = parse_event_envelope(data)
    except Exception as exc:
        logger.warning(
            "Invalid stream envelope", extra={"error": str(exc), "data": data}
        )
        return

    if not is_supported_event_version(envelope.version):
        logger.warning(
            "Unsupported stream envelope version",
            extra={"version": envelope.version},
        )
        return

    event_type = envelope.type
    if event_type != "user.transcription":
        return

    payload = envelope.payload
    user_id = envelope.user_id

    if payload is None or not user_id:
        logger.warning("Received invalid message payload or missing user_id")
        return

    payload_json = payload if isinstance(payload, str) else json.dumps(payload)

    # Deserialize event
    transcription = UserTranscriptionReceived.model_validate_json(payload_json)

    logger.info(f"Processing transcription for user {user_id}: {transcription.content}")

    # Call LLM (Gemini) with Tools
    try:
        redis = await get_redis_client()
        await _append_history(
            redis,
            user_id,
            "user",
            transcription.content,
            history_limit=HISTORY_LIMIT,
        )

        route_decision = pipeline_router.decide(transcription.content)
        logger.info(
            "Pipeline router decision",
            extra={
                "user_id": str(user_id),
                "should_parse_as_command": route_decision.should_parse_as_command,
                "reason": route_decision.reason,
            },
        )

        intent = command_parser.parse_command(
            transcription.content,
            alternatives=transcription.alternatives,
        )
        parser_command_like = bool(intent.parser_meta.get("command_like", False))
        should_fast_path_parse = (
            route_decision.should_parse_as_command or parser_command_like
        )
        logger.info(
            "Parser decision",
            extra={
                "user_id": str(user_id),
                "intent": intent.intent,
                "confidence": round(intent.confidence, 4),
                "requires_clarification": intent.requires_clarification,
                "parser_command_like": parser_command_like,
                "should_fast_path_parse": should_fast_path_parse,
            },
        )

        if should_fast_path_parse and not intent.requires_clarification:
            tool_call = _map_intent_to_tool_call(intent)
            if tool_call:
                tool_name, tool_args = tool_call
                if tool_name == "spotify.play":
                    used_cache = await _try_cached_spotify_play(
                        redis,
                        str(user_id),
                        tool_args,
                        history_limit=HISTORY_LIMIT,
                    )
                    if used_cache:
                        return
                await _execute_tool_fast(redis, str(user_id), tool_name, tool_args)
                return

        gemini = get_gemini_service()
        history = await _get_history(redis, user_id)
        cache_payload = {
            "messages": history,
            "system": SYSTEM_INSTRUCTION,
            "tools": _tools_fingerprint(),
        }
        cached_response = await redis.get(_response_cache_key(cache_payload))
        if cached_response:
            await redis.incr(_cache_hit_key())
            logger.debug("Cache hit", extra={"user_id": user_id})
            if isinstance(cached_response, bytes):
                cached_response = cached_response.decode("utf-8")
            response_event = AgentResponse(content=str(cached_response))
            await _publish_user_update(
                redis,
                event_type="agent.response",
                user_id=str(user_id),
                payload=response_event,
                metadata={"source": "llm_worker.cache_hit"},
            )
            await _append_history(
                redis,
                user_id,
                "assistant",
                str(cached_response),
                history_limit=HISTORY_LIMIT,
            )
            return
        await redis.incr(_cache_miss_key())
        logger.debug("Cache miss", extra={"user_id": user_id})
        response = await gemini.generate_chat_response(
            messages=history, system_instruction=SYSTEM_INSTRUCTION, tools=TOOLS
        )
        await _handle_llm_response(
            redis,
            user_id,
            response,
            execute_tool_call_task=execute_tool_call,
            publish_user_update=_publish_user_update,
            append_history=_append_history,
            history_limit=HISTORY_LIMIT,
        )
        try:
            if response.text:
                await redis.setex(
                    _response_cache_key(cache_payload),
                    CACHE_TTL_SECONDS,
                    response.text,
                )
        except ValueError:
            # response.text raises ValueError if content is purely function calls
            pass

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}", exc_info=True)
        if user_id:
            redis = await get_redis_client()
            if _is_quota_error(e):
                error_event = AgentError(
                    error="Gemini quota exhausted.",
                    code="gemini_quota",
                )
                await _publish_user_update(
                    redis,
                    event_type="agent.error",
                    user_id=str(user_id),
                    payload=error_event,
                    metadata={"source": "llm_worker.quota_error"},
                )
            else:
                response_event = AgentResponse(
                    content="Sorry, I ran into an error while generating a response."
                )
                await _publish_user_update(
                    redis,
                    event_type="agent.response",
                    user_id=str(user_id),
                    payload=response_event,
                    metadata={"source": "llm_worker.exception_fallback"},
                )


async def process_tool_results():
    """Listen for tool results and continue the agent loop."""
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

            try:
                envelope = parse_event_envelope(event)
            except Exception:
                continue

            if not is_supported_event_version(envelope.version):
                logger.warning(
                    "Skipping unsupported pubsub envelope version",
                    extra={"version": envelope.version},
                )
                continue

            if envelope.type != "tool.result":
                continue

            payload = envelope.payload
            user_id = envelope.user_id
            if not payload or not user_id:
                continue

            try:
                if isinstance(payload, str):
                    tool_result = ToolResult.model_validate_json(payload)
                else:
                    tool_result = ToolResult.model_validate(payload)
            except Exception:
                continue

            user_id = str(user_id)
            if tool_result.metadata and tool_result.metadata.get("fast_path"):
                continue

            await _cache_spotify_result(
                redis,
                tool_result,
                spotify_cache_ttl_seconds=SPOTIFY_CACHE_TTL_SECONDS,
            )

            response_text = format_response_text(tool_result)
            if not response_text:
                continue

            await _append_history(
                redis,
                user_id,
                "assistant",
                response_text,
                history_limit=HISTORY_LIMIT,
            )
            response_event = AgentResponse(content=response_text)
            await _publish_user_update(
                redis,
                event_type="agent.response",
                user_id=user_id,
                payload=response_event,
                metadata={"source": "llm_worker.tool_result_loop"},
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
