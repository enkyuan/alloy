"""Redis stream consumer loop with DLQ recovery."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from kaji.core.safe_logging import log_redacted_failure
from kaji.infra.realtime.dlq import drain_generic_dlq, enqueue_generic_dlq
from kaji.infra.realtime.publish import drain_user_update_outbox

logger = logging.getLogger(__name__)


SleepFn = Callable[[float], Awaitable[None]]


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
    *,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    try:
        await redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
    except Exception as error:
        if "BUSYGROUP" not in str(error):
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Error creating consumer group",
                error,
                identifiers={"group_name": group_name},
            )

    while True:
        try:
            await drain_user_update_outbox(redis)
        except Exception as error:
            log_redacted_failure(
                logger, logging.WARNING, "Failed to drain outbox", error
            )

        try:

            async def dlq_handler(redis_client, payload, **kwargs):
                return await handler_callback(
                    redis_client, payload, kwargs.get("message_id")
                )

            await drain_generic_dlq(
                redis,
                dlq_key,
                dlq_dead_key,
                dlq_max_drain,
                dlq_max_retries,
                dlq_maxlen,
                dlq_ttl,
                dlq_dead_ttl,
                dlq_handler,
            )
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Failed to drain DLQ",
                error,
                identifiers={"dlq_key": dlq_key},
            )

        try:
            messages = await redis.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_key: ">"},
                count=stream_poll_batch,
                block=200,
            )
            if not messages:
                messages = await redis.xreadgroup(
                    groupname=group_name,
                    consumername=consumer_name,
                    streams={stream_key: "0"},
                    count=stream_pending_batch,
                )
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Error reading stream",
                error,
                identifiers={"stream_key": stream_key, "group_name": group_name},
            )
            continue

        if not messages:
            await sleep(0)
            continue

        for _, stream_msgs in messages:
            for message_id, fields in stream_msgs:
                raw_payload = fields if fields else None
                handled = False
                try:
                    handled = await handler_callback(redis, raw_payload, message_id)
                except Exception as error:
                    log_redacted_failure(
                        logger,
                        logging.WARNING,
                        "Error handling stream message",
                        error,
                        identifiers={"message_id": message_id},
                    )

                enqueued = False
                if not handled:
                    try:
                        await enqueue_generic_dlq(
                            redis,
                            dlq_key,
                            raw_payload,
                            dlq_maxlen,
                            dlq_ttl,
                            reason="stream_failed",
                            attempts=1,
                            coerce_fields=dlq_coerce_fields,
                            message_id=message_id,
                        )
                        enqueued = True
                    except Exception as error:
                        log_redacted_failure(
                            logger,
                            logging.WARNING,
                            "Failed to queue DLQ",
                            error,
                            identifiers={"dlq_key": dlq_key, "message_id": message_id},
                        )
                        await sleep(0.05)

                if handled or enqueued:
                    try:
                        await redis.xack(stream_key, group_name, message_id)
                    except Exception as error:
                        log_redacted_failure(
                            logger,
                            logging.WARNING,
                            "Failed to acknowledge stream message",
                            error,
                            identifiers={
                                "stream_key": stream_key,
                                "group_name": group_name,
                                "message_id": message_id,
                            },
                        )
