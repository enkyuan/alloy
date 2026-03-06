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
import hashlib
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
from app.services.integrations.errors import IntegrationNetworkError
from app.services.parser import command_parser
from app.services.pipeline.routers.router import pipeline_router
from app.services.pipeline.services.gemini_service import get_gemini_service
from app.services.pipeline.helpers.tool_tasks import execute_tool_call
from app.services.integrations.spotify.exceptions import SpotifyAPIError
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
    publish_user_update_safely as _publish_user_update_safely,
    mark_tool_result_seen,
    parse_tool_result_dlq_entry,
    enqueue_tool_result_dlq,
    enqueue_tool_result_dlq_dead,
    drain_user_update_outbox,
    TOOL_RESULT_DLQ_KEY,
    TOOL_RESULT_DLQ_MAX_DRAIN,
    TOOL_RESULT_DLQ_MAX_RETRIES,
    TOOL_RESULT_DLQ_DEAD_KEY,
    VOICE_INPUT_DLQ_KEY,
    VOICE_INPUT_DLQ_DEAD_KEY,
    VOICE_INPUT_DLQ_MAX_DRAIN,
    VOICE_INPUT_DLQ_MAX_RETRIES,
    enqueue_voice_input_dlq,
    enqueue_voice_input_dlq_dead,
    parse_voice_input_dlq_entry,
    try_cached_spotify_play,
    is_tool_call_retry_safe,
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
SPOTIFY_CACHE_TTL_SECONDS = settings.AGENT_SPOTIFY_CACHE_TTL_SECONDS
CLIENT_HINT_CONTROL_MIN_CONFIDENCE = (
    settings.AGENT_CLIENT_HINT_CONTROL_MIN_CONFIDENCE
)
CLIENT_HINT_PLAY_MIN_CONFIDENCE = settings.AGENT_CLIENT_HINT_PLAY_MIN_CONFIDENCE
VOICE_CONSUMER_NAME = f"llm_voice_worker_{socket.gethostname()}"
TOOL_RESULTS_CONSUMER_NAME = f"llm_tool_results_worker_{socket.gethostname()}"
TOOL_CALL_DEFAULT_TIMEOUT_SECONDS = 12.0
TOOL_CALL_FAST_PATH_MAX_ATTEMPTS = 2
TOOL_CALL_FAST_PATH_BASE_RETRY_DELAY_SECONDS = 0.8
TOOL_RESULT_STREAM_POLL_BATCH = 20
TOOL_RESULT_STREAM_POLL_PENDING_BATCH = 20
VOICE_STREAM_POLL_PENDING_BATCH = 20


def _build_tool_result_dedup_key(
    tool_result: ToolResult, envelope_payload: Any
) -> str:
    if tool_result.tool_call_id:
        return tool_result.tool_call_id
    normalized = json.dumps(envelope_payload, sort_keys=True, default=str)
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return f"tool_result:legacy:{digest}"


def _coerce_voice_dlq_payload(fields: dict[str, Any] | None) -> dict[str, str]:
    if not fields:
        return {}

    def _coerce(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    return {
        _coerce(key): _coerce(value)
        for key, value in fields.items()
    }


def _extract_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    response_status_code = getattr(response, "status_code", None)
    if isinstance(response_status_code, int):
        return response_status_code

    return None


def _is_retryable_tool_error(error: Exception) -> bool:
    if isinstance(error, SpotifyAPIError):
        return bool(getattr(error, "is_retryable", False))
    if isinstance(error, IntegrationNetworkError):
        return True
    if isinstance(error, TimeoutError):
        return True

    status_code = _extract_status_code(error)
    if status_code is None:
        return False
    return status_code in {429, 500, 502, 503, 504}


def _tool_supports_fast_path_retry(tool_name: str) -> bool:
    return is_tool_call_retry_safe(tool_name)


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
    await _publish_user_update_safely(
        redis,
        event_type="tool.call",
        user_id=user_id,
        payload=tc_event,
        metadata={"source": "llm_worker.fast_path"},
        context={"tool_name": tool_name, "tool_call_id": tool_call_id},
    )

    result_data = None
    error_msg = None
    retryable = False
    last_error: Exception | None = None
    attempts = 0

    for attempts in range(1, TOOL_CALL_FAST_PATH_MAX_ATTEMPTS + 1):
        try:
            async with asyncio.timeout(TOOL_CALL_DEFAULT_TIMEOUT_SECONDS):
                async with AsyncSessionLocal() as db:
                    result_data = await execute_tool(
                        user_id, tool_name, tool_args, db
                    )
            retryable = False
            error_msg = None
            last_error = None
            break
        except TimeoutError as error:
            is_retryable = _tool_supports_fast_path_retry(tool_name)
            logger.warning(
                "Fast-path tool timed out (%s/%s)",
                attempts,
                TOOL_CALL_FAST_PATH_MAX_ATTEMPTS,
            )
            if not is_retryable:
                logger.warning(
                    "Skipping fast-path retry for non-idempotent tool on timeout",
                    extra={
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                    },
                )
            last_error = error
            retryable = is_retryable
            error_msg = "Tool execution timed out"
        except Exception as error:
            last_error = error
            retryable = (
                _is_retryable_tool_error(error)
                and _tool_supports_fast_path_retry(tool_name)
            )
            if _is_retryable_tool_error(error) and not _tool_supports_fast_path_retry(
                tool_name
            ):
                logger.warning(
                    "Skipping fast-path retry for non-idempotent tool",
                    extra={"tool_name": tool_name, "tool_call_id": tool_call_id},
                )
            error_msg = str(error)
            logger.error(
                "Fast-path tool failed: %s",
                error,
                extra={
                    "user_id": user_id,
                    "tool_name": tool_name,
                    "attempt": attempts,
                    "retryable": retryable,
                },
                exc_info=True,
            )

        if not retryable or attempts >= TOOL_CALL_FAST_PATH_MAX_ATTEMPTS:
            break

        delay = TOOL_CALL_FAST_PATH_BASE_RETRY_DELAY_SECONDS * (2 ** (attempts - 1))
        logger.warning(
            "Retrying fast-path tool execution (%s/%s)",
            attempts,
            TOOL_CALL_FAST_PATH_MAX_ATTEMPTS,
        )
        await asyncio.sleep(delay)

    if error_msg and last_error is not None:
        logger.error(
            "Fast-path tool final failure",
            extra={
                "user_id": user_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "attempts": attempts,
                "error_type": type(last_error).__name__,
                "retryable": retryable,
            },
            exc_info=True,
        )

    tool_result = ToolResult(
        tool_name=tool_name,
        tool_args=tool_args,
        result=result_data,
        error=error_msg,
        tool_call_id=tool_call_id,
        user_id=user_id,
        metadata={
            "fast_path": True,
            "attempts": attempts,
            "retryable_error": retryable,
            "error_type": type(last_error).__name__ if last_error else None,
        },
    )

    await _publish_user_update_safely(
        redis,
        event_type="tool.result",
        user_id=user_id,
        payload=tool_result,
        metadata={"source": "llm_worker.fast_path"},
        context={"tool_name": tool_name, "tool_call_id": tool_call_id},
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
        try:
            await append_history(
                redis,
                user_id,
                "assistant",
                response_text,
                history_limit=HISTORY_LIMIT,
            )
        except Exception as error:
            logger.warning(
                "Failed to append fast-path tool response to history",
                extra={"user_id": user_id, "error": str(error)},
                exc_info=True,
            )
        response_event = AgentResponse(content=response_text)
        await _publish_user_update_safely(
            redis,
            event_type="agent.response",
            user_id=user_id,
            payload=response_event,
            metadata={"source": "llm_worker.fast_path"},
            context={"tool_name": tool_name, "tool_call_id": tool_call_id},
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
    except Exception as error:
        if "BUSYGROUP" not in str(error):
            logger.error("Error creating consumer group: %s", error)

    logger.info("LLM Worker started listening on %s", RedisKeys.STREAM_VOICE_INPUT)

    while True:
        try:
            try:
                await drain_user_update_outbox(redis)
            except Exception as error:
                logger.warning("Failed to drain user update outbox: %s", error)
            try:
                await _drain_voice_input_dlq(redis)
            except Exception as error:
                logger.warning("Failed to drain voice input DLQ: %s", error)

            # Read from stream using consumer group
            streams = await redis.xreadgroup(
                groupname=RedisKeys.GROUP_LLM_WORKER,
                consumername=VOICE_CONSUMER_NAME,
                streams={RedisKeys.STREAM_VOICE_INPUT: ">"},
                count=1,
                block=2000,
            )
            if not streams:
                streams = await redis.xreadgroup(
                    groupname=RedisKeys.GROUP_LLM_WORKER,
                    consumername=VOICE_CONSUMER_NAME,
                    streams={RedisKeys.STREAM_VOICE_INPUT: "0"},
                    count=VOICE_STREAM_POLL_PENDING_BATCH,
                )

            if not streams:
                continue

            for _, messages in streams:
                for message_id, data in messages:
                    handled = False
                    try:
                        await handle_message(data)
                        handled = True
                    except Exception as error:
                        handled = False
                        logger.error(
                            "Error processing message %s: %s",
                            message_id,
                            error,
                            exc_info=True,
                        )
                    if handled:
                        try:
                            await redis.xack(
                                RedisKeys.STREAM_VOICE_INPUT,
                                RedisKeys.GROUP_LLM_WORKER,
                                message_id,
                            )
                        except Exception as error:
                            logger.warning(
                                "Failed to ack message %s: %s",
                                message_id,
                                error,
                            )
                        continue

                    try:
                        await enqueue_voice_input_dlq(
                            redis,
                            _coerce_voice_dlq_payload(data),
                            reason="voice_input_stream_failed",
                            attempts=1,
                            message_id=str(message_id),
                        )
                    except Exception as dlq_error:
                        logger.warning(
                            "Failed to enqueue failed voice stream message to DLQ",
                            extra={
                                "message_id": message_id,
                                "dlq_error": str(dlq_error),
                            },
                            exc_info=True,
                        )
                        await asyncio.sleep(0.05)
                        continue

                    try:
                        await redis.xack(
                            RedisKeys.STREAM_VOICE_INPUT,
                            RedisKeys.GROUP_LLM_WORKER,
                            message_id,
                        )
                    except Exception as error:
                        logger.warning(
                            "Failed to ack failed voice stream message %s: %s",
                            message_id,
                            error,
                            exc_info=True,
                        )

        except Exception as error:
            logger.error("Error in LLM worker loop: %s", error)
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
        try:
            await append_history(
                redis,
                user_id,
                "assistant",
                response_text,
                history_limit=HISTORY_LIMIT,
            )
        except Exception as error:
            logger.warning(
                "Failed to append clarification response to history",
                extra={"user_id": user_id, "error": str(error)},
                exc_info=True,
            )
        response_event = AgentResponse(content=response_text)
        await _publish_user_update_safely(
            redis,
            event_type="agent.response",
            user_id=user_id,
            payload=response_event,
            metadata={"source": "llm_worker.spotify_clarification"},
            context={"action": clarification_resolution.action},
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
    await _publish_user_update_safely(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "llm_worker.cache_hit"},
        context={"source": "cache"},
    )
    try:
        await append_history(
            redis,
            user_id,
            "assistant",
            str(cached_response),
            history_limit=HISTORY_LIMIT,
        )
    except Exception as error:
        logger.warning(
            "Failed to append cached response to history",
            extra={"user_id": user_id, "error": str(error)},
            exc_info=True,
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
        append_history=append_history,
        history_limit=HISTORY_LIMIT,
    )
    response_text: str | None = None
    try:
        response_text = response.text
    except ValueError:
        # response.text raises ValueError when the response is function calls only.
        logger.debug(
            "Skipping response cache because Gemini response has no text content",
            extra={"user_id": user_id},
        )

    if response_text:
        await redis.setex(
            response_cache_key(cache_payload),
            CACHE_TTL_SECONDS,
            response_text,
        )
    logger.info(
        "Completed LLM response",
        extra={"user_id": user_id, "elapsed_ms": _elapsed_ms(started_at)},
    )


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

    logger.info(
        "Processing transcription for user %s",
        user_id,
        extra={"transcription_length": len(transcription.content)},
    )

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

    except Exception as error:
        logger.error("LLM generation failed: %s", error, exc_info=True)
        if user_id:
            redis = await get_redis_client()
            if _is_quota_error(error):
                error_event = AgentError(
                    error="Gemini quota exhausted.",
                    code="gemini_quota",
                )
                await _publish_user_update_safely(
                    redis,
                    event_type="agent.error",
                    user_id=str(user_id),
                    payload=error_event,
                    metadata={"source": "llm_worker.quota_error"},
                    context={"error_type": "quota"},
                )
            else:
                response_event = AgentResponse(
                    content="Sorry, I ran into an error while generating a response."
                )
                await _publish_user_update_safely(
                    redis,
                    event_type="agent.response",
                    user_id=str(user_id),
                    payload=response_event,
                    metadata={"source": "llm_worker.exception_fallback"},
                    context={"error_type": "fallback"},
                )


async def _handle_tool_result_envelope(redis: Any, raw: Any) -> bool:
    if not raw:
        return True

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    if isinstance(raw, dict):
        event = raw
    else:
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            logger.warning(
                "Failed to decode tool.result envelope JSON",
                extra={"raw": str(raw)[:200]},
            )
            return False

    try:
        envelope = parse_event_envelope(event)
    except Exception as error:
        logger.warning(
            "Invalid tool.result envelope",
            extra={"error": str(error)},
            exc_info=True,
        )
        return False

    if not is_supported_event_version(envelope.version):
        logger.warning(
            "Skipping unsupported tool.result envelope version",
            extra={"version": envelope.version},
        )
        return True

    if envelope.type != "tool.result":
        return True

    payload = envelope.payload
    user_id = envelope.user_id
    if not payload or not user_id:
        logger.warning("Skipping tool.result with missing payload or user_id")
        return True

    try:
        if isinstance(payload, str):
            tool_result = ToolResult.model_validate_json(payload)
        else:
            tool_result = ToolResult.model_validate(payload)
    except Exception as error:
        logger.warning(
            "Failed to validate tool.result payload",
            extra={"user_id": str(user_id), "error": str(error)},
            exc_info=True,
        )
        return False

    user_id_str = str(user_id)
    dedupe_key = _build_tool_result_dedup_key(tool_result, payload)
    if not await mark_tool_result_seen(redis, tool_call_id=dedupe_key):
        logger.warning(
            "Skipping duplicate tool.result message",
            extra={
                "tool_call_id": tool_result.tool_call_id,
                "tool_name": tool_result.tool_name,
                "user_id": user_id_str,
                "dedupe_key": dedupe_key,
            },
        )
        return True

    await cache_spotify_result(
        redis,
        tool_result,
        spotify_cache_ttl_seconds=SPOTIFY_CACHE_TTL_SECONDS,
    )
    await cache_spotify_clarification(
        redis,
        user_id=user_id_str,
        tool_result=tool_result,
    )

    response_text = format_response_text(tool_result)
    if not response_text:
        return True

    try:
        await append_history(
            redis,
            user_id_str,
            "assistant",
            response_text,
            history_limit=HISTORY_LIMIT,
        )
    except Exception as error:
        logger.warning(
            "Failed to append tool result response to history",
            extra={"user_id": user_id_str, "error": str(error)},
            exc_info=True,
        )

    response_event = AgentResponse(content=response_text)
    await _publish_user_update_safely(
        redis,
        event_type="agent.response",
        user_id=user_id_str,
        payload=response_event,
        metadata={"source": "llm_worker.tool_result_loop"},
        context={"tool_call_id": tool_result.tool_call_id or dedupe_key},
    )
    return True


async def _drain_tool_result_dlq(redis: Any) -> None:
    drained = 0
    for _ in range(TOOL_RESULT_DLQ_MAX_DRAIN):
        raw = await redis.rpop(TOOL_RESULT_DLQ_KEY)
        if not raw:
            break

        payload, attempts, reason = parse_tool_result_dlq_entry(raw)
        handled = False
        try:
            handled = await _handle_tool_result_envelope(redis, payload)
        except Exception as error:
            logger.warning(
                "Error handling tool.result from dead-letter queue",
                extra={"error": str(error), "attempts": attempts},
                exc_info=True,
            )

        if handled:
            drained += 1
            continue

        next_attempt = attempts + 1
        next_reason = reason or "tool_result_dlq_retry"
        if next_attempt > TOOL_RESULT_DLQ_MAX_RETRIES:
            try:
                await enqueue_tool_result_dlq_dead(
                    redis,
                    payload,
                    reason=next_reason,
                    attempts=next_attempt,
                )
                logger.error(
                    "Tool result dead-letter entry exhausted retries",
                    extra={
                        "tool_result_dlq_dead_key": TOOL_RESULT_DLQ_DEAD_KEY,
                        "attempts": next_attempt,
                        "reason": next_reason,
                    },
                )
            except Exception as error:
                logger.warning(
                    "Failed to move exhausted tool result DLQ entry to dead queue",
                    extra={"attempts": next_attempt, "error": str(error)},
                    exc_info=True,
                )
            continue

        try:
            await enqueue_tool_result_dlq(
                redis,
                payload,
                reason=next_reason,
                attempts=next_attempt,
            )
            logger.warning(
                "Requeued failed tool result dead-letter payload for retry",
                extra={
                    "attempts": next_attempt,
                    "reason": next_reason,
                    "dlq_key": TOOL_RESULT_DLQ_KEY,
                },
            )
        except Exception as error:
            logger.warning(
                "Failed to requeue tool result DLQ payload for retry",
                extra={"attempts": next_attempt, "error": str(error)},
                exc_info=True,
            )
    if drained:
        logger.info("Processed tool result dead-letter messages", extra={"drained": drained})


async def _drain_voice_input_dlq(redis: Any) -> None:
    drained = 0
    for _ in range(VOICE_INPUT_DLQ_MAX_DRAIN):
        raw = await redis.rpop(VOICE_INPUT_DLQ_KEY)
        if not raw:
            break

        payload, attempts, reason, message_id = parse_voice_input_dlq_entry(raw)
        handled = False
        try:
            await handle_message(payload)
            handled = True
        except Exception as error:
            logger.warning(
                "Error handling voice input from dead-letter queue",
                extra={
                    "message_id": message_id,
                    "attempts": attempts,
                    "reason": reason,
                    "error": str(error),
                },
                exc_info=True,
            )

        if handled:
            drained += 1
            continue

        next_attempt = attempts + 1
        next_reason = reason or "voice_input_dlq_retry"
        if next_attempt > VOICE_INPUT_DLQ_MAX_RETRIES:
            try:
                await enqueue_voice_input_dlq_dead(
                    redis,
                    payload,
                    reason=next_reason,
                    attempts=next_attempt,
                    message_id=message_id,
                )
                logger.error(
                    "Voice input dead-letter entry exhausted retries",
                    extra={
                        "voice_input_dlq_dead_key": VOICE_INPUT_DLQ_DEAD_KEY,
                        "attempts": next_attempt,
                        "reason": next_reason,
                        "message_id": message_id,
                    },
                )
            except Exception as error:
                logger.warning(
                    "Failed to move exhausted voice input DLQ entry to dead queue",
                    extra={"attempts": next_attempt, "error": str(error)},
                    exc_info=True,
                )
            continue

        try:
            await enqueue_voice_input_dlq(
                redis,
                payload,
                reason=next_reason,
                attempts=next_attempt,
                message_id=message_id,
            )
            logger.warning(
                "Requeued failed voice input message for retry",
                extra={
                    "attempts": next_attempt,
                    "reason": next_reason,
                    "message_id": message_id,
                },
            )
        except Exception as error:
            logger.warning(
                "Failed to requeue failed voice input payload for retry",
                extra={"attempts": next_attempt, "error": str(error)},
                exc_info=True,
            )
    if drained:
        logger.info(
            "Processed voice input dead-letter messages",
            extra={"drained": drained},
        )


async def process_tool_results():
    """Listen for tool results and continue the agent loop."""
    redis = await get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(RedisKeys.CHANNEL_USER_UPDATES)

    try:
        await redis.xgroup_create(
            RedisKeys.STREAM_TOOL_RESULTS,
            RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
            id="0",
            mkstream=True,
        )
    except Exception as error:
        if "BUSYGROUP" not in str(error):
            logger.warning(
                "Error creating tool result consumer group: %s",
                error,
                exc_info=True,
            )

    logger.info("LLM Worker listening for tool results")
    try:
        while True:
            try:
                await drain_user_update_outbox(redis)
            except Exception as error:
                logger.warning("Failed to drain user update outbox: %s", error)

            try:
                await _drain_tool_result_dlq(redis)
            except Exception as error:
                logger.warning("Failed to drain tool result DLQ: %s", error)

            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.25
            )
            if message is not None:
                pubsub_handled = False
                try:
                    pubsub_handled = await _handle_tool_result_envelope(
                        redis, message.get("data")
                    )
                except Exception as error:
                    logger.warning(
                        "Error handling tool.result from pubsub",
                        extra={"message": message},
                        exc_info=True,
                    )
                if not pubsub_handled:
                    try:
                        await enqueue_tool_result_dlq(
                            redis,
                            message.get("data"),
                            reason="tool_result_pubsub_failed",
                        )
                    except Exception as dlq_error:
                        logger.warning(
                            "Failed to enqueue failed pubsub tool.result payload to DLQ",
                            extra={"dlq_error": str(dlq_error)},
                            exc_info=True,
                        )

            try:
                stream_messages = await redis.xreadgroup(
                    groupname=RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
                    consumername=TOOL_RESULTS_CONSUMER_NAME,
                    streams={RedisKeys.STREAM_TOOL_RESULTS: ">"},
                    count=TOOL_RESULT_STREAM_POLL_BATCH,
                    block=200,
                )
                if not stream_messages:
                    stream_messages = await redis.xreadgroup(
                        groupname=RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
                        consumername=TOOL_RESULTS_CONSUMER_NAME,
                        streams={RedisKeys.STREAM_TOOL_RESULTS: "0"},
                        count=TOOL_RESULT_STREAM_POLL_PENDING_BATCH,
                    )
            except Exception as error:
                logger.warning("Error reading tool result stream: %s", error)
                continue

            if not stream_messages:
                await asyncio.sleep(0)
                continue

            for _, messages in stream_messages:
                for message_id, fields in messages:
                    raw_payload = fields.get("payload") if fields else None
                    handled = False
                    try:
                        handled = await _handle_tool_result_envelope(
                            redis, raw_payload
                        )
                    except Exception as error:
                        logger.warning(
                            "Error handling tool.result from stream",
                            extra={"message_id": message_id},
                            exc_info=True,
                        )
                    enqueued = False
                    if not handled:
                        logger.warning(
                            "Requeuing failed tool.result stream message to DLQ",
                            extra={"message_id": message_id},
                        )
                        try:
                            await enqueue_tool_result_dlq(
                                redis,
                                raw_payload,
                                reason="tool_result_stream_failed",
                            )
                            enqueued = True
                        except Exception as dlq_error:
                            logger.warning(
                                "Failed to enqueue failed tool.result payload to DLQ",
                                extra={
                                    "message_id": message_id,
                                    "dlq_error": str(dlq_error),
                                },
                                exc_info=True,
                            )
                            await asyncio.sleep(0.05)
                    if handled or enqueued:
                        try:
                            await redis.xack(
                                RedisKeys.STREAM_TOOL_RESULTS,
                                RedisKeys.GROUP_LLM_WORKER_TOOL_RESULTS,
                                message_id,
                            )
                        except Exception as error:
                            logger.warning(
                                "Failed to ack tool result stream message",
                                extra={"message_id": message_id},
                                exc_info=True,
                            )
                            logger.debug("Tool result stream ack failed: %s", error)
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
