"""Redis user-update publishing, stream fanout, and outbox recovery."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import asyncio

from kaji.infra.events.envelope import build_event_envelope, to_redis_stream_fields
from kaji.infra.realtime.redis import RedisConfig, RedisKeys
from kaji.infra.realtime.common import (
    append_to_list_with_ttl,
    coerce_str_payload,
)

logger = logging.getLogger(__name__)


def _unwrap_outbox_item(raw_payload: Any) -> bytes:
    if isinstance(raw_payload, bytes):
        payload_text = raw_payload.decode("utf-8", errors="replace")
    else:
        payload_text = coerce_str_payload(raw_payload)

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


async def _publish_with_retry(
    redis: Any,
    *,
    channel: str,
    user_id: str,
    event_type: str,
    payload_bytes: bytes,
    max_attempts: int = RedisConfig.TOOL_RESULT_PUBLISH_MAX_ATTEMPTS,
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
                    await append_to_list_with_ttl(
                        redis,
                        key=RedisKeys.USER_UPDATE_OUTBOX_KEY,
                        payload=json.dumps(outbox_item, ensure_ascii=False),
                        maxlen=RedisConfig.USER_UPDATE_OUTBOX_MAXLEN,
                        ttl_seconds=RedisConfig.USER_UPDATE_OUTBOX_TTL_SECONDS,
                    )
                    logger.warning(
                        "Enqueued failed publish payload to user update outbox",
                        extra={
                            "outbox_key": RedisKeys.USER_UPDATE_OUTBOX_KEY,
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
                        await append_to_list_with_ttl(
                            redis,
                            key=RedisKeys.USER_UPDATE_OUTBOX_DLQ_KEY,
                            payload=json.dumps(dlq_item, ensure_ascii=False),
                            maxlen=RedisConfig.USER_UPDATE_OUTBOX_DLQ_MAXLEN,
                            ttl_seconds=RedisConfig.USER_UPDATE_OUTBOX_DLQ_TTL_SECONDS,
                        )
                    except Exception:
                        logger.error(
                            "Failed to enqueue user update publish failure to DLQ",
                            extra={
                                "user_id": user_id,
                                "event_type": event_type,
                                "outbox_key": RedisKeys.USER_UPDATE_OUTBOX_KEY,
                                "dlq_key": RedisKeys.USER_UPDATE_OUTBOX_DLQ_KEY,
                                "outbox_error": str(outbox_error),
                            },
                            exc_info=True,
                        )
                    logger.error(
                        "Failed to enqueue user update publish failure for outbox",
                        extra={
                            "user_id": user_id,
                            "event_type": event_type,
                            "outbox_key": RedisKeys.USER_UPDATE_OUTBOX_KEY,
                        },
                        exc_info=True,
                    )
                raise

            delay = RedisConfig.TOOL_RESULT_PUBLISH_BASE_RETRY_DELAY_SECONDS * (
                2 ** (attempt - 1)
            )
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
    max_items: int = RedisConfig.USER_UPDATE_OUTBOX_MAX_DRAIN,
) -> int:
    drained = 0
    for _ in range(max_items):
        raw = await redis.rpop(RedisKeys.USER_UPDATE_OUTBOX_KEY)
        if not raw:
            break

        payload_bytes = _unwrap_outbox_item(raw)

        try:
            await redis.publish(channel, payload_bytes)
            drained += 1
        except Exception:
            await redis.rpush(RedisKeys.USER_UPDATE_OUTBOX_KEY, raw)
            logger.warning(
                "Failed to flush user update outbox item",
                extra={"outbox_key": RedisKeys.USER_UPDATE_OUTBOX_KEY},
            )
            break

    if drained:
        logger.info(
            "Flushed user update outbox",
            extra={"drained": drained, "outbox_key": RedisKeys.USER_UPDATE_OUTBOX_KEY},
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
                maxlen=RedisConfig.TOOL_RESULT_STREAM_MAXLEN,
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
