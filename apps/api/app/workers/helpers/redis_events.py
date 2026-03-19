"""
Redis and event helper functions for the LLM worker.
"""

import base64
import json
import logging
import uuid
import asyncio
from typing import Any

import msgpack

from app.core.events import (
    AgentResponse,
    ToolCall,
    ToolResult,
    build_event_envelope,
    to_redis_stream_fields,
)
from app.core.redis import RedisKeys
from app.workers.helpers.cache_keys import spotify_cache_key

logger = logging.getLogger(__name__)
from app.workers.helpers.redis_constants import *

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


def _encode_msgpack_base64(payload: Any) -> str:
    packed = msgpack.packb(payload, use_bin_type=True)
    return base64.b64encode(packed).decode("ascii")


def _decode_msgpack_base64(payload_b64: str) -> Any:
    packed = base64.b64decode(payload_b64.encode("ascii"), validate=True)
    return msgpack.unpackb(packed, raw=False, strict_map_key=False)


def _unwrap_outbox_item(raw_payload: Any) -> bytes:
    if isinstance(raw_payload, bytes):
        payload_text = raw_payload.decode("utf-8", errors="replace")
    else:
        payload_text = _coerce_str_payload(raw_payload)

    try:
        parsed = json.loads(payload_text)
    except json.JSONDecodeError:
        return payload_text.encode("utf-8")
    if not isinstance(parsed, dict):
        return payload_text.encode("utf-8")

    payload_b64 = parsed.get("payload_b64")
    if isinstance(payload_b64, str):
        try:
            return base64.b64decode(payload_b64.encode("ascii"), validate=True)
        except Exception:
            return payload_text.encode("utf-8")

    return payload_text.encode("utf-8")


async def _append_to_list_with_ttl(
    redis: Any,
    *,
    key: str,
    payload: Any,
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


def build_generic_dlq_entry(
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
    coerce_fields: bool = False,
    **kwargs: Any,
) -> str:
    data = {
        "reason": reason,
        "attempts": attempts,
    }
    if coerce_fields and isinstance(payload, dict):
        data["payload"] = {
            _coerce_str_payload(k): _coerce_str_payload(v) for k, v in payload.items()
        }
    elif coerce_fields:
        data["payload"] = _coerce_str_payload(payload)
    else:
        try:
            data["payload_msgpack_b64"] = _encode_msgpack_base64(payload)
        except Exception:
            data["payload"] = _coerce_str_payload(payload)

    data.update({k: v for k, v in kwargs.items() if v is not None})
    return json.dumps(data, ensure_ascii=False, default=str)


def parse_generic_dlq_entry(
    raw: Any,
) -> tuple[Any, int, str | None, dict[str, Any]]:
    payload = _coerce_str_payload(raw)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return payload, 0, None, {}

    if not isinstance(data, dict):
        return payload, 0, None, {}

    payload_value = None
    payload_msgpack_b64 = data.pop("payload_msgpack_b64", None)
    if isinstance(payload_msgpack_b64, str):
        try:
            payload_value = _decode_msgpack_base64(payload_msgpack_b64)
        except Exception:
            payload_value = None

    if payload_value is None:
        payload_value = data.pop("payload", None)
    if isinstance(payload_value, str):
        try:
            nested_payload = json.loads(payload_value)
            if isinstance(nested_payload, dict):
                payload_value = nested_payload
        except json.JSONDecodeError:
            pass

    attempts = data.pop("attempts", 0)
    try:
        attempts = int(attempts)
    except (TypeError, ValueError):
        attempts = 0

    reason = data.pop("reason", None)
    return payload_value, attempts, str(reason) if reason else None, data


async def enqueue_generic_dlq(
    redis: Any,
    queue_key: str,
    payload: Any,
    maxlen: int,
    ttl_seconds: int,
    *,
    reason: str | None = None,
    attempts: int = 0,
    coerce_fields: bool = False,
    **kwargs: Any,
) -> None:
    entry = build_generic_dlq_entry(
        payload, reason=reason, attempts=attempts, coerce_fields=coerce_fields, **kwargs
    )
    await _append_to_list_with_ttl(
        redis,
        key=queue_key,
        payload=entry,
        maxlen=maxlen,
        ttl_seconds=ttl_seconds,
    )


async def drain_generic_dlq(
    redis: Any,
    dlq_key: str,
    dead_key: str,
    max_drain: int,
    max_retries: int,
    maxlen: int,
    ttl_seconds: int,
    dead_ttl_seconds: int,
    handler_callback: Any,
) -> int:
    drained = 0
    for _ in range(max_drain):
        raw = await redis.rpop(dlq_key)
        if not raw:
            break

        payload, attempts, reason, extras = parse_generic_dlq_entry(raw)
        handled = False
        try:
            handled = await handler_callback(redis, payload, **extras)
        except Exception as error:
            logger.warning(
                "Error handling DLQ entry",
                extra={"error": str(error), "attempts": attempts, "dlq_key": dlq_key},
                exc_info=True,
            )

        if handled:
            drained += 1
            continue

        next_attempt = attempts + 1
        next_reason = reason or "dlq_retry"
        if next_attempt > max_retries:
            try:
                await enqueue_generic_dlq(
                    redis, dead_key, payload, maxlen, dead_ttl_seconds,
                    reason=next_reason, attempts=next_attempt, **extras
                )
                logger.error(
                    "DLQ dead-letter entry exhausted retries",
                    extra={"dead_key": dead_key, "attempts": next_attempt, "reason": next_reason, **extras},
                )
            except Exception as error:
                logger.warning(
                    "Failed to move exhausted DLQ entry to dead queue",
                    extra={"attempts": next_attempt, "error": str(error)},
                    exc_info=True,
                )
            continue

        try:
            await enqueue_generic_dlq(
                redis, dlq_key, payload, maxlen, ttl_seconds,
                reason=next_reason, attempts=next_attempt, **extras
            )
            logger.warning(
                "Requeued failed dead-letter payload for retry",
                extra={"attempts": next_attempt, "reason": next_reason, "dlq_key": dlq_key, **extras},
            )
        except Exception as error:
            logger.warning(
                "Failed to requeue DLQ payload for retry",
                extra={"attempts": next_attempt, "error": str(error)},
                exc_info=True,
            )
    if drained:
        logger.info("Processed dead-letter messages", extra={"drained": drained, "dlq_key": dlq_key})
    return drained


async def append_history(
    redis: Any,
    user_id: str,
    role: str,
    content: str,
    *,
    history_limit: int,
) -> None:
    key = history_key(user_id)
    entry = {"role": role, "content": content}

    # Skip exact consecutive duplicates to prevent runaway history growth.
    last_item = await redis.lindex(key, -1)
    if last_item:
        try:
            if isinstance(last_item, bytes):
                last_item = last_item.decode("utf-8")
            last_entry = json.loads(last_item)
            if (
                isinstance(last_entry, dict)
                and str(last_entry.get("role")) == role
                and str(last_entry.get("content")) == content
            ):
                return
        except Exception:
            logger.warning("Skipping invalid history tail entry", exc_info=True)

    await redis.rpush(key, json.dumps(entry))
    if history_limit > 0:
        await redis.ltrim(key, -history_limit, -1)


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
    payload_bytes: bytes,
    max_attempts: int = TOOL_RESULT_PUBLISH_MAX_ATTEMPTS,
) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            await redis.publish(channel, payload_bytes)
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
                    "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
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
                        "payload_b64": outbox_item["payload_b64"],
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

        payload_bytes = _unwrap_outbox_item(raw)

        try:
            await redis.publish(channel, payload_bytes)
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
    payload_bytes = to_redis_stream_fields(envelope)["_msgpack"]

    if event_type == "tool.result":
        try:
            await redis.xadd(
                RedisKeys.STREAM_TOOL_RESULTS,
                {"_msgpack": payload_bytes},
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
        payload_bytes=payload_bytes,
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
        metadata={"source": "agent.cached_spotify_play"},
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
        metadata={"source": "agent.cached_spotify_play"},
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

async def run_stream_with_dlq(
    redis: Any,
    stream_key: str,
    group_name: str,
    consumer_name: str,
    dlq_key: str,
    dlq_dead_key: str,
    dlq_max_drain: int,
    dlq_max_retries: int,
    dlq_maxlen: int,
    dlq_ttl: int,
    dlq_dead_ttl: int,
    stream_poll_batch: int,
    stream_pending_batch: int,
    handler_callback: Any,
    dlq_coerce_fields: bool = False,
):
    try:
        await redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
    except Exception as error:
        if "BUSYGROUP" not in str(error):
            logger.warning("Error creating consumer group %s: %s", group_name, error)
            
    while True:
        try:
            await drain_user_update_outbox(redis)
        except Exception as error:
            logger.warning("Failed to drain outbox: %s", error)

        try:
            async def dlq_handler(redis_client, payload, **kwargs):
                return await handler_callback(redis_client, payload, kwargs.get("message_id"))
            
            await drain_generic_dlq(
                redis, dlq_key, dlq_dead_key, dlq_max_drain, dlq_max_retries,
                dlq_maxlen, dlq_ttl, dlq_dead_ttl, dlq_handler
            )
        except Exception as error:
            logger.warning("Failed to drain DLQ: %s", error)

        try:
            messages = await redis.xreadgroup(
                groupname=group_name, consumername=consumer_name,
                streams={stream_key: ">"}, count=stream_poll_batch, block=200,
            )
            if not messages:
                messages = await redis.xreadgroup(
                    groupname=group_name, consumername=consumer_name,
                    streams={stream_key: "0"}, count=stream_pending_batch,
                )
        except Exception as error:
            logger.warning("Error reading stream %s: %s", stream_key, error)
            continue

        if not messages:
            await asyncio.sleep(0)
            continue

        for _, stream_msgs in messages:
            for message_id, fields in stream_msgs:
                raw_payload = fields if fields else None
                handled = False
                try:
                    handled = await handler_callback(redis, raw_payload, message_id)
                except Exception as error:
                    logger.warning("Error handling message %s: %s", message_id, error, exc_info=True)

                enqueued = False
                if not handled:
                    try:
                        await enqueue_generic_dlq(
                            redis, dlq_key, raw_payload, dlq_maxlen, dlq_ttl,
                            reason="stream_failed", attempts=1, coerce_fields=dlq_coerce_fields, message_id=message_id
                        )
                        enqueued = True
                    except Exception as error:
                        logger.warning("Failed to queue DLQ: %s", error)
                        await asyncio.sleep(0.05)
                
                if handled or enqueued:
                    try:
                        await redis.xack(stream_key, group_name, message_id)
                    except Exception as error:
                        logger.warning("Failed to xack %s: %s", message_id, error)
