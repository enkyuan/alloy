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
import socket
import uuid
from typing import Any, Optional

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.events import (
    AgentError,
    AgentResponse,
    ToolCall,
    ToolResult,
    UserTranscriptionReceived,
    is_supported_event_version,
    parse_event_envelope,
)
from app.core.prompts import ASSISTANT_SYSTEM_INSTRUCTION
from app.core.redis import RedisKeys, get_redis_client
from app.services.integrations.dispatcher import execute_tool
from app.services.parser import command_parser
from app.services.pipeline.routers.router import pipeline_router
from app.services.pipeline.services.gemini_service import get_gemini_service
from app.services.pipeline.helpers.tool_tasks import execute_tool_call
from app.workers.helpers.cache_keys import (
    cache_hit_key,
    cache_miss_key,
    response_cache_key,
)
from app.workers.helpers.clarification_state import (
    cache_spotify_clarification,
    clear_spotify_clarification_state,
    resolve_spotify_clarification,
)
from app.workers.helpers.intent_mapping import (
    map_intent_to_tool_call,
)
from app.workers.helpers.llm_response import (
    handle_llm_response,
)
from app.workers.helpers.redis_events import (
    append_history,
    cache_spotify_result,
    get_history,
    publish_user_update,
    try_cached_spotify_play,
)
from app.workers.helpers.response_text import format_response_text
from app.workers.helpers.tools_payload import (
    build_tools_payload,
    tools_fingerprint,
)

logger = logging.getLogger(__name__)

# Normalize optional config to concrete ints for downstream helpers.
HISTORY_LIMIT: int = settings.AGENT_HISTORY_LIMIT or 0
CACHE_TTL_SECONDS = settings.AGENT_CACHE_TTL_SECONDS
SECONDS_PER_HOUR = 3600
SPOTIFY_CACHE_TTL_SECONDS = SECONDS_PER_HOUR
CLIENT_HINT_CONTROL_MIN_CONFIDENCE = 0.82
CLIENT_HINT_PLAY_MIN_CONFIDENCE = 0.93
CONSUMER_NAME = f"llm_worker_{socket.gethostname()}_{uuid.uuid4().hex[:8]}"


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


def _elapsed_ms(started_at: float) -> int:
    return int((asyncio.get_running_loop().time() - started_at) * 1000)


def _coerce_hint_confidence(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(float(value), 1.0))
    if isinstance(value, str):
        try:
            return max(0.0, min(float(value), 1.0))
        except ValueError:
            return 0.0
    return 0.0


def _map_client_parse_hint_to_tool_call(
    parse_hint: Optional[dict[str, Any]],
    *,
    route_is_command_like: bool,
) -> tuple[str, dict[str, Any]] | None:
    if not parse_hint or not route_is_command_like:
        return None

    raw_intent = str(parse_hint.get("intent", "")).strip().lower()
    confidence = _coerce_hint_confidence(parse_hint.get("confidence"))
    query_value = str(parse_hint.get("query", "")).strip()

    if raw_intent == "pause" and confidence >= CLIENT_HINT_CONTROL_MIN_CONFIDENCE:
        return "spotify.pause", {}
    if raw_intent == "resume" and confidence >= CLIENT_HINT_CONTROL_MIN_CONFIDENCE:
        return "spotify.resume", {}
    if raw_intent == "next" and confidence >= CLIENT_HINT_CONTROL_MIN_CONFIDENCE:
        return "spotify.next", {}
    if raw_intent == "previous" and confidence >= CLIENT_HINT_CONTROL_MIN_CONFIDENCE:
        return "spotify.previous", {}
    if (
        raw_intent == "play"
        and query_value
        and confidence >= CLIENT_HINT_PLAY_MIN_CONFIDENCE
    ):
        return "spotify.play", {"query": query_value}

    return None


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
    await publish_user_update(
        redis,
        event_type="tool.call",
        user_id=user_id,
        payload=tc_event,
        metadata={"source": "llm_worker.fast_path"},
    )

    result_data = None
    error_msg = None
    try:
        async with AsyncSessionLocal() as db:
            result_data = await execute_tool(user_id, tool_name, tool_args, db)
    except Exception as e:
        logger.error(f"Fast-path tool failed: {e}", exc_info=True)
        error_msg = str(e)

    tool_result = ToolResult(
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_data,
        error=error_msg,
        tool_call_id=tool_call_id,
        user_id=user_id,
        metadata={"fast_path": True},
    )

    await publish_user_update(
        redis,
        event_type="tool.result",
        user_id=user_id,
        payload=tool_result,
        metadata={"source": "llm_worker.fast_path"},
    )

    await cache_spotify_result(
        redis,
        tool_result,
        spotify_cache_ttl_seconds=SPOTIFY_CACHE_TTL_SECONDS,
    )
    await cache_spotify_clarification(
        redis,
        user_id=user_id,
        tool_result=tool_result,
    )

    response_text = format_response_text(tool_result)
    if response_text:
        await append_history(
            redis,
            user_id,
            "assistant",
            response_text,
            history_limit=HISTORY_LIMIT,
        )
        response_event = AgentResponse(content=response_text)
        await publish_user_update(
            redis,
            event_type="agent.response",
            user_id=user_id,
            payload=response_event,
            metadata={"source": "llm_worker.fast_path"},
        )


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
                consumername=CONSUMER_NAME,
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


async def _try_clarification_resolution(
    redis: Any,
    *,
    user_id: str,
    transcription: UserTranscriptionReceived,
    started_at: float,
) -> bool:
    clarification_resolution = await resolve_spotify_clarification(
        redis,
        user_id=user_id,
        user_text=transcription.content,
    )
    if not clarification_resolution:
        return False

    if clarification_resolution.action == "play_uri":
        tool_args = clarification_resolution.tool_args or {}
        await clear_spotify_clarification_state(redis, user_id)
        await _execute_tool_fast(redis, user_id, "spotify.play", tool_args)
        logger.info(
            "Resolved spotify clarification transaction",
            extra={
                "user_id": user_id,
                "tool_args": tool_args,
                "elapsed_ms": _elapsed_ms(started_at),
            },
        )
        return True

    if clarification_resolution.action == "respond":
        response_text = clarification_resolution.response_text or (
            "Please choose one of the options."
        )
        await append_history(
            redis,
            user_id,
            "assistant",
            response_text,
            history_limit=HISTORY_LIMIT,
        )
        response_event = AgentResponse(content=response_text)
        await publish_user_update(
            redis,
            event_type="agent.response",
            user_id=user_id,
            payload=response_event,
            metadata={"source": "llm_worker.spotify_clarification"},
        )
        logger.info(
            "Replied with spotify clarification reminder",
            extra={"user_id": user_id, "elapsed_ms": _elapsed_ms(started_at)},
        )
        return True

    return False


async def _try_client_hint_fast_path(
    redis: Any,
    *,
    user_id: str,
    transcription: UserTranscriptionReceived,
    route_decision: Any,
    started_at: float,
) -> bool:
    hint_tool_call = _map_client_parse_hint_to_tool_call(
        transcription.parse_hint,
        route_is_command_like=route_decision.should_parse_as_command,
    )
    if not hint_tool_call:
        return False

    hinted_tool_name, hinted_tool_args = hint_tool_call
    logger.info(
        "Executing client-hinted fast path",
        extra={
            "user_id": user_id,
            "tool_name": hinted_tool_name,
            "tool_args": hinted_tool_args,
            "hint": transcription.parse_hint or {},
        },
    )
    if hinted_tool_name == "spotify.play":
        used_cache = await try_cached_spotify_play(
            redis,
            user_id,
            hinted_tool_args,
            history_limit=HISTORY_LIMIT,
        )
        if used_cache:
            return True

    await _execute_tool_fast(redis, user_id, hinted_tool_name, hinted_tool_args)
    logger.info(
        "Completed client-hinted fast path",
        extra={
            "user_id": user_id,
            "tool_name": hinted_tool_name,
            "elapsed_ms": _elapsed_ms(started_at),
        },
    )
    return True


async def _try_parser_fast_path(
    redis: Any,
    *,
    user_id: str,
    transcription: UserTranscriptionReceived,
    route_decision: Any,
    started_at: float,
) -> bool:
    intent = command_parser.parse_command(
        transcription.content,
        alternatives=transcription.alternatives,
    )
    parser_command_like = bool(intent.parser_meta.get("command_like", False))
    should_fast_path_parse = route_decision.should_parse_as_command or parser_command_like
    logger.info(
        "Parser decision",
        extra={
            "user_id": user_id,
            "intent": intent.intent,
            "confidence": round(intent.confidence, 4),
            "requires_clarification": intent.requires_clarification,
            "parser_command_like": parser_command_like,
            "should_fast_path_parse": should_fast_path_parse,
        },
    )
    if not should_fast_path_parse or intent.requires_clarification:
        return False

    tool_call = map_intent_to_tool_call(intent)
    if not tool_call:
        return False

    tool_name, tool_args = tool_call
    if tool_name == "spotify.play":
        used_cache = await try_cached_spotify_play(
            redis,
            user_id,
            tool_args,
            history_limit=HISTORY_LIMIT,
        )
        if used_cache:
            logger.info(
                "Completed parser fast path using cached spotify result",
                extra={
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            return True

    await _execute_tool_fast(redis, user_id, tool_name, tool_args)
    logger.info(
        "Completed parser fast path",
        extra={
            "user_id": user_id,
            "tool_name": tool_name,
            "elapsed_ms": _elapsed_ms(started_at),
        },
    )
    return True


def _build_response_cache_payload(history: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "messages": history,
        "system": ASSISTANT_SYSTEM_INSTRUCTION,
        "tools": tools_fingerprint(),
    }


async def _try_cached_response(
    redis: Any,
    *,
    user_id: str,
    history: list[dict[str, Any]],
    cache_payload: dict[str, Any],
) -> bool:
    cached_response = await redis.get(response_cache_key(cache_payload))
    if not cached_response:
        await redis.incr(cache_miss_key())
        logger.debug("Cache miss", extra={"user_id": user_id})
        return False

    await redis.incr(cache_hit_key())
    logger.debug("Cache hit", extra={"user_id": user_id})
    if isinstance(cached_response, bytes):
        cached_response = cached_response.decode("utf-8")

    response_event = AgentResponse(content=str(cached_response))
    await publish_user_update(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "llm_worker.cache_hit"},
    )
    await append_history(
        redis,
        user_id,
        "assistant",
        str(cached_response),
        history_limit=HISTORY_LIMIT,
    )
    return True


async def _run_llm_fallback(
    redis: Any,
    *,
    user_id: str,
    history: list[dict[str, Any]],
    cache_payload: dict[str, Any],
    started_at: float,
) -> None:
    gemini = get_gemini_service()
    tools_payload = build_tools_payload()
    response = await gemini.generate_chat_response(
        messages=history,
        system_instruction=ASSISTANT_SYSTEM_INSTRUCTION,
        tools=tools_payload,
    )
    await handle_llm_response(
        redis,
        user_id,
        response,
        execute_tool_call_task=execute_tool_call,
        publish_user_update=publish_user_update,
        append_history=append_history,
        history_limit=HISTORY_LIMIT,
    )
    try:
        if response.text:
            await redis.setex(
                response_cache_key(cache_payload),
                CACHE_TTL_SECONDS,
                response.text,
            )
        logger.info(
            "Completed LLM response",
            extra={"user_id": user_id, "elapsed_ms": _elapsed_ms(started_at)},
        )
    except ValueError:
        # response.text raises ValueError if content is purely function calls
        pass


async def handle_message(data: dict):
    """Business logic for handling a single voice event."""
    started_at = asyncio.get_running_loop().time()
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

    try:
        redis = await get_redis_client()
        await append_history(
            redis,
            user_id,
            "user",
            transcription.content,
            history_limit=HISTORY_LIMIT,
        )

        user_id_str = str(user_id)
        if await _try_clarification_resolution(
            redis,
            user_id=user_id_str,
            transcription=transcription,
            started_at=started_at,
        ):
            return

        route_decision = pipeline_router.decide(transcription.content)
        logger.info(
            "Pipeline router decision",
            extra={
                "user_id": user_id_str,
                "should_parse_as_command": route_decision.should_parse_as_command,
                "reason": route_decision.reason,
            },
        )

        if await _try_client_hint_fast_path(
            redis,
            user_id=user_id_str,
            transcription=transcription,
            route_decision=route_decision,
            started_at=started_at,
        ):
            return

        if await _try_parser_fast_path(
            redis,
            user_id=user_id_str,
            transcription=transcription,
            route_decision=route_decision,
            started_at=started_at,
        ):
            return

        history = await get_history(redis, user_id)
        cache_payload = _build_response_cache_payload(history)
        if await _try_cached_response(
            redis,
            user_id=user_id_str,
            history=history,
            cache_payload=cache_payload,
        ):
            return

        await _run_llm_fallback(
            redis,
            user_id=user_id_str,
            history=history,
            cache_payload=cache_payload,
            started_at=started_at,
        )

    except Exception as e:
        logger.error(f"LLM Generation failed: {e}", exc_info=True)
        if user_id:
            redis = await get_redis_client()
            if _is_quota_error(e):
                error_event = AgentError(
                    error="Gemini quota exhausted.",
                    code="gemini_quota",
                )
                await publish_user_update(
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
                await publish_user_update(
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

            await cache_spotify_result(
                redis,
                tool_result,
                spotify_cache_ttl_seconds=SPOTIFY_CACHE_TTL_SECONDS,
            )
            await cache_spotify_clarification(
                redis,
                user_id=user_id,
                tool_result=tool_result,
            )

            response_text = format_response_text(tool_result)
            if not response_text:
                continue

            await append_history(
                redis,
                user_id,
                "assistant",
                response_text,
                history_limit=HISTORY_LIMIT,
            )
            response_event = AgentResponse(content=response_text)
            await publish_user_update(
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
