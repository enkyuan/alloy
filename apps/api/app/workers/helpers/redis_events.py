"""
Redis and event helper functions for the LLM worker.
"""

import json
import logging
import uuid
import asyncio
from typing import Any

from app.core.events import AgentResponse, ToolCall, ToolResult, build_event_envelope
from app.core.redis import RedisKeys
from app.workers.helpers.cache_keys import spotify_cache_key

logger = logging.getLogger(__name__)
TOOL_RESULT_PUBLISH_MAX_ATTEMPTS = 3
TOOL_RESULT_PUBLISH_BASE_RETRY_DELAY_SECONDS = 0.25
TOOL_RESULT_STREAM_MAXLEN = 10_000
USER_UPDATE_OUTBOX_KEY = "outbox:user_updates:v1"
USER_UPDATE_OUTBOX_MAXLEN = 2_000
USER_UPDATE_OUTBOX_MAX_DRAIN = 100
USER_UPDATE_OUTBOX_TTL_SECONDS = 24 * 60 * 60
USER_UPDATE_OUTBOX_DLQ_KEY = "dlq:user_updates:v1"
USER_UPDATE_OUTBOX_DLQ_MAXLEN = 2_000
USER_UPDATE_OUTBOX_DLQ_TTL_SECONDS = 7 * 24 * 60 * 60
TOOL_RESULT_DLQ_KEY = "dlq:tool_results:v1"
TOOL_RESULT_DLQ_DEAD_KEY = "dlq:tool_results:dead:v1"
TOOL_RESULT_DLQ_MAXLEN = 2_000
TOOL_RESULT_DLQ_MAX_DRAIN = 25
TOOL_RESULT_DLQ_MAX_RETRIES = 3
TOOL_RESULT_DLQ_TTL_SECONDS = 24 * 60 * 60
TOOL_RESULT_DLQ_DEAD_TTL_SECONDS = 7 * 24 * 60 * 60
VOICE_INPUT_DLQ_KEY = "dlq:voice_input:v1"
VOICE_INPUT_DLQ_DEAD_KEY = "dlq:voice_input:dead:v1"
VOICE_INPUT_DLQ_MAXLEN = 2_000
VOICE_INPUT_DLQ_MAX_DRAIN = 25
VOICE_INPUT_DLQ_MAX_RETRIES = 3
VOICE_INPUT_DLQ_TTL_SECONDS = 24 * 60 * 60
VOICE_INPUT_DLQ_DEAD_TTL_SECONDS = 7 * 24 * 60 * 60
TOOL_RESULT_SEEN_KEY_PREFIX = "tool_result:seen:v1:"
TOOL_RESULT_SEEN_TTL_SECONDS = 24 * 60 * 60
TOOL_CALL_RETRYABLE_TOOL_NAMES: frozenset[str] = frozenset({"spotify.list_devices"})
TOOL_CALL_DEDUP_IN_PROGRESS_PREFIX = "tool_call:inflight:v1:"
TOOL_CALL_DEDUP_DONE_PREFIX = "tool_call:done:v1:"
TOOL_CALL_DEDUP_TTL_SECONDS = 24 * 60 * 60
TOOL_CALL_DEDUP_IN_PROGRESS_TTL_SECONDS = 5 * 60


def history_key(user_id: str) -> str:
    return f"agent:history:{user_id}"


def tool_result_seen_key(tool_call_id: str) -> str:
    return f"{TOOL_RESULT_SEEN_KEY_PREFIX}{tool_call_id}"


def tool_call_in_progress_key(tool_call_id: str) -> str:
    return f"{TOOL_CALL_DEDUP_IN_PROGRESS_PREFIX}{tool_call_id}"


def tool_call_done_key(tool_call_id: str) -> str:
    return f"{TOOL_CALL_DEDUP_DONE_PREFIX}{tool_call_id}"


def is_tool_call_retry_safe(tool_name: str) -> bool:
    return tool_name in TOOL_CALL_RETRYABLE_TOOL_NAMES


def _coerce_str_payload(payload: Any) -> str:
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError:
        return str(payload)


def _unwrap_outbox_item(raw_payload: Any) -> str:
    payload = _coerce_str_payload(raw_payload)
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    if not isinstance(parsed, dict):
        return payload
    value = parsed.get("payload")
    if value is None:
        return payload
    return _coerce_str_payload(value)


async def _append_to_list_with_ttl(
    redis: Any,
    *,
    key: str,
    payload: str,
    maxlen: int,
    ttl_seconds: int,
) -> None:
    await redis.lpush(key, payload)
    if maxlen > 0:
        await redis.ltrim(key, 0, maxlen - 1)
    if ttl_seconds > 0:
        await redis.expire(key, ttl_seconds)


async def publish_user_update_safely(
    redis: Any,
    *,
    channel: str = RedisKeys.CHANNEL_USER_UPDATES,
    event_type: str,
    user_id: str,
    payload: Any,
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    try:
        await publish_user_update(
            redis,
            channel=channel,
            event_type=event_type,
            user_id=user_id,
            payload=payload,
            metadata=metadata,
        )
        return True
    except Exception as error:
        logger.warning(
            "Failed to publish user update",
            extra={
                "event_type": event_type,
                "user_id": user_id,
                "context": context or {},
                "error": str(error),
            },
            exc_info=True,
        )
        return False


def build_tool_result_dlq_entry(
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
) -> str:
    return json.dumps(
        {
            "payload": _coerce_str_payload(payload),
            "reason": reason,
            "attempts": attempts,
        },
        ensure_ascii=False,
    )


def parse_tool_result_dlq_entry(raw: Any) -> tuple[str, int, str | None]:
    payload = _coerce_str_payload(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload, 0, None

    if not isinstance(data, dict):
        return payload, 0, None

    payload_value = data.get("payload")
    if payload_value is None:
        return payload, 0, None

    attempts = data.get("attempts", 0)
    try:
        attempts_value = int(attempts)
    except (TypeError, ValueError):
        attempts_value = 0

    reason = data.get("reason")
    return (
        _coerce_str_payload(payload_value),
        attempts_value,
        str(reason) if isinstance(reason, str) else None,
    )


async def enqueue_tool_result_dlq(
    redis: Any,
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
) -> None:
    await _append_to_list_with_ttl(
        redis,
        key=TOOL_RESULT_DLQ_KEY,
        payload=build_tool_result_dlq_entry(payload, reason=reason, attempts=attempts),
        maxlen=TOOL_RESULT_DLQ_MAXLEN,
        ttl_seconds=TOOL_RESULT_DLQ_TTL_SECONDS,
    )


async def enqueue_tool_result_dlq_dead(
    redis: Any,
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = TOOL_RESULT_DLQ_MAX_RETRIES,
) -> None:
    await _append_to_list_with_ttl(
        redis,
        key=TOOL_RESULT_DLQ_DEAD_KEY,
        payload=json.dumps(
            {
                "payload": _coerce_str_payload(payload),
                "reason": reason,
                "attempts": attempts,
            },
            ensure_ascii=False,
        ),
        maxlen=TOOL_RESULT_DLQ_MAXLEN,
        ttl_seconds=TOOL_RESULT_DLQ_DEAD_TTL_SECONDS,
    )


def _coerce_str_fields(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {"payload": _coerce_str_payload(payload)}

    return {
        _coerce_str_payload(key): _coerce_str_payload(value)
        for key, value in payload.items()
    }


def build_voice_input_dlq_entry(
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
    message_id: str | None = None,
) -> str:
    return json.dumps(
        {
            "payload": _coerce_str_fields(payload),
            "reason": reason,
            "attempts": attempts,
            "message_id": message_id,
        },
        ensure_ascii=False,
    )


def parse_voice_input_dlq_entry(
    raw: Any,
) -> tuple[dict[str, Any], int, str | None, str | None]:
    payload = _coerce_str_payload(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {"payload": payload}, 0, None, None

    if not isinstance(data, dict):
        return {"payload": payload}, 0, None, None

    payload_value = data.get("payload")
    if isinstance(payload_value, str):
        try:
            nested_payload = json.loads(payload_value)
            if isinstance(nested_payload, dict):
                payload_value = nested_payload
        except json.JSONDecodeError:
            pass

    if not isinstance(payload_value, dict):
        if payload_value is None:
            return {}, 0, None, None
        return {"payload": payload_value}, 0, None, None

    attempts_value = data.get("attempts", 0)
    try:
        attempts = int(attempts_value)
    except (TypeError, ValueError):
        attempts = 0

    message_id_value = data.get("message_id")
    message_id = str(message_id_value) if message_id_value is not None else None
    reason_value = data.get("reason")
    reason = reason_value if isinstance(reason_value, str) else None
    return payload_value, attempts, reason, message_id


async def enqueue_voice_input_dlq(
    redis: Any,
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
    message_id: str | None = None,
) -> None:
    await _append_to_list_with_ttl(
        redis,
        key=VOICE_INPUT_DLQ_KEY,
        payload=build_voice_input_dlq_entry(
            payload,
            reason=reason,
            attempts=attempts,
            message_id=message_id,
        ),
        maxlen=VOICE_INPUT_DLQ_MAXLEN,
        ttl_seconds=VOICE_INPUT_DLQ_TTL_SECONDS,
    )


async def enqueue_voice_input_dlq_dead(
    redis: Any,
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = VOICE_INPUT_DLQ_MAX_RETRIES,
    message_id: str | None = None,
) -> None:
    await _append_to_list_with_ttl(
        redis,
        key=VOICE_INPUT_DLQ_DEAD_KEY,
        payload=build_voice_input_dlq_entry(
            payload,
            reason=reason,
            attempts=attempts,
            message_id=message_id,
        ),
        maxlen=VOICE_INPUT_DLQ_MAXLEN,
        ttl_seconds=VOICE_INPUT_DLQ_DEAD_TTL_SECONDS,
    )


async def append_history(
    redis: Any,
    user_id: str,
    role: str,
    content: str,
    *,
    history_limit: int,
) -> None:
    entry = {"role": role, "content": content}
    await redis.rpush(history_key(user_id), json.dumps(entry))
    if history_limit > 0:
        await redis.ltrim(history_key(user_id), -history_limit, -1)


async def get_history(redis: Any, user_id: str) -> list[dict[str, str]]:
    raw_items = await redis.lrange(history_key(user_id), 0, -1)
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
            logger.warning("Skipping invalid history entry", exc_info=True)
            continue
    return messages


async def _publish_with_retry(
    redis: Any,
    *,
    channel: str,
    user_id: str,
    event_type: str,
    payload_json: str,
    max_attempts: int = TOOL_RESULT_PUBLISH_MAX_ATTEMPTS,
) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            await redis.publish(channel, payload_json)
            return
        except Exception as error:
            if attempt >= max_attempts:
                logger.error(
                    "Failed to publish user update after retries",
                    extra={
                        "user_id": user_id,
                        "event_type": event_type,
                        "attempt": attempt,
                        "error": str(error),
                    },
                    exc_info=True,
                )
                outbox_item = {
                    "payload": payload_json,
                    "user_id": user_id,
                    "event_type": event_type,
                }
                try:
                    await _append_to_list_with_ttl(
                        redis,
                        key=USER_UPDATE_OUTBOX_KEY,
                        payload=json.dumps(outbox_item, ensure_ascii=False),
                        maxlen=USER_UPDATE_OUTBOX_MAXLEN,
                        ttl_seconds=USER_UPDATE_OUTBOX_TTL_SECONDS,
                    )
                    logger.warning(
                        "Enqueued failed publish payload to user update outbox",
                        extra={
                            "outbox_key": USER_UPDATE_OUTBOX_KEY,
                            "user_id": user_id,
                            "event_type": event_type,
                        },
                    )
                except Exception as outbox_error:
                    dlq_item = {
                        "payload": payload_json,
                        "user_id": user_id,
                        "event_type": event_type,
                        "error": str(outbox_error),
                        "reason": "publish_outbox_enqueue_failed",
                    }
                    try:
                        await _append_to_list_with_ttl(
                            redis,
                            key=USER_UPDATE_OUTBOX_DLQ_KEY,
                            payload=json.dumps(dlq_item, ensure_ascii=False),
                            maxlen=USER_UPDATE_OUTBOX_DLQ_MAXLEN,
                            ttl_seconds=USER_UPDATE_OUTBOX_DLQ_TTL_SECONDS,
                        )
                    except Exception:
                        logger.error(
                            "Failed to enqueue user update publish failure to DLQ",
                            extra={
                                "user_id": user_id,
                                "event_type": event_type,
                                "outbox_key": USER_UPDATE_OUTBOX_KEY,
                                "dlq_key": USER_UPDATE_OUTBOX_DLQ_KEY,
                                "outbox_error": str(outbox_error),
                            },
                            exc_info=True,
                        )
                    logger.error(
                        "Failed to enqueue user update publish failure for outbox",
                        extra={
                            "user_id": user_id,
                            "event_type": event_type,
                            "outbox_key": USER_UPDATE_OUTBOX_KEY,
                        },
                        exc_info=True,
                    )
                raise

            delay = TOOL_RESULT_PUBLISH_BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Retrying user update publish after publish error (%s/%s)",
                attempt,
                max_attempts,
            )
            await asyncio.sleep(delay)


async def drain_user_update_outbox(
    redis: Any,
    *,
    channel: str = RedisKeys.CHANNEL_USER_UPDATES,
    max_items: int = USER_UPDATE_OUTBOX_MAX_DRAIN,
) -> int:
    drained = 0
    for _ in range(max_items):
        raw = await redis.rpop(USER_UPDATE_OUTBOX_KEY)
        if not raw:
            break

        payload_json = _unwrap_outbox_item(raw)

        try:
            await redis.publish(channel, payload_json)
            drained += 1
        except Exception:
            await redis.rpush(USER_UPDATE_OUTBOX_KEY, raw)
            logger.warning(
                "Failed to flush user update outbox item",
                extra={"outbox_key": USER_UPDATE_OUTBOX_KEY},
            )
            break

    if drained:
        logger.info(
            "Flushed user update outbox",
            extra={"drained": drained, "outbox_key": USER_UPDATE_OUTBOX_KEY},
        )
    return drained


async def publish_user_update(
    redis: Any,
    *,
    channel: str = RedisKeys.CHANNEL_USER_UPDATES,
    event_type: str,
    user_id: str,
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    envelope = build_event_envelope(
        event_type=event_type,
        user_id=user_id,
        payload=payload,
        metadata=metadata or {},
    )
    payload_json = json.dumps(envelope)

    if event_type == "tool.result":
        try:
            await redis.xadd(
                RedisKeys.STREAM_TOOL_RESULTS,
                {"payload": payload_json},
                maxlen=TOOL_RESULT_STREAM_MAXLEN,
                approximate=True,
            )
        except Exception:
            logger.warning(
                "Failed to append tool.result to stream",
                extra={
                    "event_type": event_type,
                    "user_id": user_id,
                    "stream": RedisKeys.STREAM_TOOL_RESULTS,
                },
                exc_info=True,
            )

    await _publish_with_retry(
        redis,
        channel=channel,
        user_id=user_id,
        event_type=event_type,
        payload_json=payload_json,
    )


async def mark_tool_result_seen(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return False
    return bool(
        await redis.set(
            tool_result_seen_key(tool_call_id),
            "1",
            ex=TOOL_RESULT_SEEN_TTL_SECONDS,
            nx=True,
        )
    )


async def claim_tool_call_execution(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return True
    return bool(
        await redis.set(
            tool_call_in_progress_key(tool_call_id),
            "1",
            ex=TOOL_CALL_DEDUP_IN_PROGRESS_TTL_SECONDS,
            nx=True,
        )
    )


async def is_tool_call_execution_complete(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return False
    return bool(await redis.get(tool_call_done_key(tool_call_id)))


async def mark_tool_call_execution_complete(redis: Any, *, tool_call_id: str) -> None:
    if not tool_call_id:
        return
    done_key = tool_call_done_key(tool_call_id)
    progress_key = tool_call_in_progress_key(tool_call_id)
    await redis.set(done_key, "1", ex=TOOL_CALL_DEDUP_TTL_SECONDS)
    await redis.delete(progress_key)


async def clear_tool_call_execution_in_progress(
    redis: Any, *, tool_call_id: str
) -> None:
    if not tool_call_id:
        return
    await redis.delete(tool_call_in_progress_key(tool_call_id))


async def cache_spotify_result(
    redis: Any,
    tool_result: ToolResult,
    *,
    spotify_cache_ttl_seconds: int,
) -> None:
    if tool_result.tool_name != "spotify.play":
        return
    if not isinstance(tool_result.result, dict):
        return
    data = tool_result.result.get("data")
    if not isinstance(data, dict):
        return

    uri = data.get("uri")
    track_name = data.get("track_name")
    artist = data.get("artist")
    if not uri or not track_name:
        return

    query = tool_result.tool_args.get("query") if tool_result.tool_args else None
    if not query:
        query = track_name

    cache_key = spotify_cache_key(str(query), str(artist) if artist else None)
    payload = {
        "uri": uri,
        "track_name": track_name,
        "artist": artist,
    }
    await redis.setex(cache_key, spotify_cache_ttl_seconds, json.dumps(payload))
    logger.info(
        "Cached Spotify play result",
        extra={
            "cache_key": cache_key,
            "track_name": str(track_name),
            "artist": str(artist) if artist else "",
        },
    )


async def try_cached_spotify_play(
    redis: Any,
    user_id: str,
    tool_args: dict[str, Any],
    *,
    history_limit: int,
) -> bool:
    query = str(tool_args.get("query", "")).strip()
    if not query:
        return False

    artist = tool_args.get("artist")
    cache_key = spotify_cache_key(query, str(artist) if artist else None)
    cached = await redis.get(cache_key)
    if not cached:
        logger.debug(
            "No cached Spotify track for query",
            extra={"user_id": user_id, "query": query, "cache_key": cache_key},
        )
        return False

    try:
        payload = json.loads(cached)
    except Exception:
        logger.warning(
            "Invalid cached Spotify payload",
            extra={"user_id": user_id, "cache_key": cache_key},
            exc_info=True,
        )
        return False

    uri = payload.get("uri")
    if not uri:
        return False

    tool_call_id = str(uuid.uuid4())
    tool_call_event = ToolCall(
        tool_name="spotify.play",
        tool_args={"uri": uri},
        tool_call_id=tool_call_id,
    )
    published = await publish_user_update_safely(
        redis,
        event_type="tool.call",
        user_id=user_id,
        payload=tool_call_event,
        metadata={"source": "llm_worker.cached_spotify_play"},
        context={"source": "cached_spotify_play", "tool_call_id": tool_call_id},
    )
    if not published:
        logger.warning(
            "Failed to publish cached spotify play tool.call event",
            extra={"user_id": user_id, "source": "tool.call"},
        )

    track_name = payload.get("track_name")
    artist_name = payload.get("artist")
    if track_name and artist_name:
        response_text = f"Playing {track_name} by {artist_name}."
    elif track_name:
        response_text = f"Playing {track_name}."
    else:
        response_text = "Playing on Spotify."

    await append_history(
        redis,
        user_id,
        "assistant",
        response_text,
        history_limit=history_limit,
    )
    response_event = AgentResponse(content=response_text)
    published = await publish_user_update_safely(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "llm_worker.cached_spotify_play"},
        context={"source": "cached_spotify_play", "tool_call_id": tool_call_id},
    )
    if not published:
        logger.warning(
            "Failed to publish cached spotify play agent response",
            extra={"user_id": user_id},
        )
    logger.info(
        "Served Spotify play request from cache",
        extra={"user_id": user_id, "query": query, "cache_key": cache_key},
    )
    return True
