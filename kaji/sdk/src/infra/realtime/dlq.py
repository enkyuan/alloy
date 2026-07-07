"""Generic Redis dead-letter queue helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from kaji.infra.realtime.common import (
    append_to_list_with_ttl,
    coerce_str_payload,
    decode_msgpack_base64,
    encode_msgpack_base64,
)

logger = logging.getLogger(__name__)


def build_generic_dlq_entry(
    payload: Any,
    *,
    reason: str | None = None,
    attempts: int = 0,
    coerce_fields: bool = False,
    **kwargs: Any,
) -> str:
    data: dict[str, Any] = {
        "reason": reason,
        "attempts": attempts,
    }
    if coerce_fields and isinstance(payload, dict):
        data["payload"] = {
            coerce_str_payload(k): coerce_str_payload(v) for k, v in payload.items()
        }
    elif coerce_fields:
        data["payload"] = coerce_str_payload(payload)
    else:
        try:
            data["payload_msgpack_b64"] = encode_msgpack_base64(payload)
        except Exception:
            data["payload"] = coerce_str_payload(payload)

    data.update({k: v for k, v in kwargs.items() if v is not None})
    return json.dumps(data, ensure_ascii=False, default=str)


def parse_generic_dlq_entry(
    raw: Any,
) -> tuple[Any, int, str | None, dict[str, Any]]:
    payload = coerce_str_payload(raw)
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
            payload_value = decode_msgpack_base64(payload_msgpack_b64)
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
    await append_to_list_with_ttl(
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
                    redis,
                    dead_key,
                    payload,
                    maxlen,
                    dead_ttl_seconds,
                    reason=next_reason,
                    attempts=next_attempt,
                    **extras,
                )
                logger.error(
                    "DLQ dead-letter entry exhausted retries",
                    extra={
                        "dead_key": dead_key,
                        "attempts": next_attempt,
                        "reason": next_reason,
                        **extras,
                    },
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
                redis,
                dlq_key,
                payload,
                maxlen,
                ttl_seconds,
                reason=next_reason,
                attempts=next_attempt,
                **extras,
            )
            logger.warning(
                "Requeued failed dead-letter payload for retry",
                extra={
                    "attempts": next_attempt,
                    "reason": next_reason,
                    "dlq_key": dlq_key,
                    **extras,
                },
            )
        except Exception as error:
            logger.warning(
                "Failed to requeue DLQ payload for retry",
                extra={"attempts": next_attempt, "error": str(error)},
                exc_info=True,
            )
    if drained:
        logger.info(
            "Processed dead-letter messages",
            extra={"drained": drained, "dlq_key": dlq_key},
        )
    return drained
