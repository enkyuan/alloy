import asyncio
import logging
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from kaji.infra.events.envelope import (
    is_supported_event_version,
    parse_event_envelope,
)
from kaji.modalities.voice.event_registry import EventInstance, EventsRegistry
from kaji.infra.realtime.redis import (
    RedisKeys,
    get_redis_client,
    get_redis_stream_client,
)
from kaji_serve.runtime.messaging import Bus, Message
from kaji.infra.realtime.publish import publish_user_update_safely
from kaji.infra.realtime.streams import run_stream_with_dlq

logger = logging.getLogger(__name__)


def _parse_event_envelope(envelope: Dict[str, Any]) -> List[EventInstance]:
    try:
        parsed = parse_event_envelope(envelope)
    except Exception as exc:
        logger.warning("Invalid event envelope: %s", exc)
        return []

    if not is_supported_event_version(parsed.version):
        logger.warning("Unsupported event version: %s", parsed.version)
        return []

    event_cls = EventsRegistry.get_type(parsed.type)
    if event_cls is None:
        return []

    try:
        event = event_cls.model_validate(parsed.payload)
    except Exception as exc:
        logger.warning("Failed to parse event payload for %s: %s", parsed.type, exc)
        return []

    if (
        hasattr(event, "user_id")
        and getattr(event, "user_id") is None
        and parsed.user_id
    ):
        try:
            setattr(event, "user_id", str(parsed.user_id))
        except Exception as exc:
            logger.debug("Could not set user_id on event: %s", exc)

    return [event]


def _parse_stream_payload(payload: Any) -> Dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    msgpack_payload = payload.get("_msgpack")
    if msgpack_payload is None:
        msgpack_payload = payload.get(b"_msgpack")

    if not isinstance(msgpack_payload, (bytes, bytearray, memoryview)):
        return None

    return {"_msgpack": bytes(msgpack_payload)}


class RedisStreamInput:
    """Input source that reads Agent events from a Redis stream."""

    def __init__(
        self,
        stream: str = RedisKeys.STREAM_AGENT_INPUT,
        group: str = RedisKeys.GROUP_LLM_WORKER,
        consumer: str = RedisKeys.CONSUMER_LLM_WORKER,
        block_ms: int = 2000,
    ):
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.block_ms = block_ms
        self._initialized = False

    async def _ensure_group(self):
        if self._initialized:
            return
        redis = await get_redis_stream_client()
        try:
            await redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.warning("Redis stream group error: %s", exc)
        else:
            logger.info(
                "Redis stream group ready",
                extra={"stream": self.stream, "group": self.group},
            )
        self._initialized = True

    async def get(self) -> Dict[str, Any]:
        await self._ensure_group()
        redis = await get_redis_stream_client()

        while True:
            streams = await redis.xreadgroup(
                groupname=self.group,
                consumername=self.consumer,
                streams={self.stream: ">"},
                count=1,
                block=self.block_ms,
            )
            if not streams:
                continue

            for _, messages in streams:
                for message_id, data in messages:
                    try:
                        await redis.xack(self.stream, self.group, message_id)
                    except Exception as exc:
                        logger.debug("Redis xack failed: %s", exc)
                    logger.debug(
                        "Received stream event",
                        extra={"stream": self.stream, "message_id": message_id},
                    )
                    return dict(data)

    async def consume_to_bus(
        self,
        node_id: str,
        bus: Bus,
        dlq_key: str,
        dlq_dead_key: str,
        dlq_max_drain: int,
        dlq_max_retries: int,
        dlq_maxlen: int,
        dlq_ttl: int,
        dlq_dead_ttl: int,
        stream_poll_batch: int = 20,
        stream_pending_batch: int = 20,
        dlq_coerce_fields: bool = False,
    ) -> None:
        redis = await get_redis_stream_client()

        async def _bus_handler(redis_client, payload, message_id):
            parsed_payload = _parse_stream_payload(payload)
            if parsed_payload is None:
                logger.warning(
                    "Dropping non-msgpack stream payload",
                    extra={"stream": self.stream, "message_id": message_id},
                )
                return True

            events = self.map_to_events(parsed_payload)
            success = False
            for event in events:
                await bus.broadcast(Message(source=node_id, event=event))
                success = True
            return success

        await run_stream_with_dlq(
            redis,
            self.stream,
            self.group,
            self.consumer,
            dlq_key,
            dlq_dead_key,
            dlq_max_drain,
            dlq_max_retries,
            dlq_maxlen,
            dlq_ttl,
            dlq_dead_ttl,
            stream_poll_batch,
            stream_pending_batch,
            _bus_handler,
            dlq_coerce_fields,
        )

    def map_to_events(self, message: Dict[str, Any]) -> Iterable[EventInstance]:
        return _parse_event_envelope(message)


class RedisPubSubInput:
    """Input source that listens to Agent pubsub events."""

    def __init__(
        self,
        channel: str = RedisKeys.CHANNEL_USER_UPDATES,
        allowed_types: Optional[set[str]] = None,
    ):
        self.channel = channel
        self.allowed_types = allowed_types
        self._pubsub = None

    async def _ensure_subscription(self):
        if self._pubsub is not None:
            return
        redis = await get_redis_stream_client()
        self._pubsub = redis.pubsub()
        await self._pubsub.subscribe(self.channel)
        logger.info("Subscribed to Redis channel", extra={"channel": self.channel})

    async def get(self) -> Dict[str, Any]:
        await self._ensure_subscription()
        assert self._pubsub is not None

        while True:
            message = await self._pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue

            data = message.get("data")
            if not data:
                continue

            try:
                envelope = parse_event_envelope(data).model_dump()
            except Exception:
                continue

            event_type = envelope.get("type")
            if self.allowed_types and event_type not in self.allowed_types:
                continue

            logger.debug(
                "Received pubsub event",
                extra={"channel": self.channel, "type": event_type},
            )
            return envelope

    def map_to_events(self, message: Dict[str, Any]) -> Iterable[EventInstance]:
        return _parse_event_envelope(message)


class RedisPublisher:
    """Publishes agent events to the Agent Redis channel."""

    def __init__(self, channel: str = RedisKeys.CHANNEL_USER_UPDATES):
        self.channel = channel

    async def publish(
        self, user_id: str, event: BaseModel, event_type: Optional[str] = None
    ) -> None:
        redis = await get_redis_client()
        event_alias = event_type or EventsRegistry.get_alias(type(event))
        if not event_alias:
            logger.warning("No alias registered for event %s", type(event).__name__)
            return
        if hasattr(event, "user_id") and getattr(event, "user_id") is None:
            try:
                setattr(event, "user_id", user_id)
            except Exception as exc:
                logger.debug("Could not set user_id on event: %s", exc)

        published = await publish_user_update_safely(
            redis,
            channel=self.channel,
            event_type=event_alias,
            user_id=user_id,
            payload=event,
            metadata={"source": "RedisPublisher.publish"},
        )
        if published:
            logger.debug(
                "Published event",
                extra={
                    "channel": self.channel,
                    "type": event_alias,
                    "user_id": user_id,
                },
            )
        else:
            logger.warning(
                "Failed to publish event; outbox fallback may apply",
                extra={
                    "channel": self.channel,
                    "type": event_alias,
                    "user_id": user_id,
                },
            )
