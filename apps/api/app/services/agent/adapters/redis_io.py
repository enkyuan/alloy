import asyncio
import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from app.core.events import EventInstance, EventsRegistry
from app.core.redis import RedisKeys, get_redis_client

logger = logging.getLogger(__name__)


def _parse_event_envelope(envelope: Dict[str, Any]) -> List[EventInstance]:
    event_type = envelope.get("type")
    payload = envelope.get("payload")
    user_id = envelope.get("user_id")

    if not event_type or payload is None:
        return []

    event_cls = EventsRegistry.get_type(event_type)
    if event_cls is None:
        return []

    try:
        if isinstance(payload, str):
            event = event_cls.model_validate_json(payload)
        else:
            event = event_cls.model_validate(payload)
    except Exception as exc:
        logger.warning(f"Failed to parse event payload for {event_type}: {exc}")
        return []

    if hasattr(event, "user_id") and getattr(event, "user_id") is None and user_id:
        try:
            setattr(event, "user_id", str(user_id))
        except Exception:
            pass

    return [event]


class RedisStreamInput:
    """Input source that reads Agent events from a Redis stream."""

    def __init__(
        self,
        stream: str = RedisKeys.STREAM_VOICE_INPUT,
        group: str = RedisKeys.GROUP_LLM_WORKER,
        consumer: str = "bus_worker",
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
        redis = await get_redis_client()
        try:
            await redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.warning(f"Redis stream group error: {exc}")
        else:
            logger.info(
                "Redis stream group ready",
                extra={"stream": self.stream, "group": self.group},
            )
        self._initialized = True

    async def get(self) -> Dict[str, Any]:
        await self._ensure_group()
        redis = await get_redis_client()

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
                        logger.debug(f"Redis xack failed: {exc}")
                    logger.debug(
                        "Received stream event",
                        extra={"stream": self.stream, "message_id": message_id},
                    )
                    return dict(data)

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
        redis = await get_redis_client()
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
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                envelope = json.loads(data)
            except json.JSONDecodeError:
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
            logger.warning(f"No alias registered for event {type(event).__name__}")
            return
        if hasattr(event, "user_id") and getattr(event, "user_id") is None:
            try:
                setattr(event, "user_id", user_id)
            except Exception:
                pass

        payload = event.model_dump_json()
        await redis.publish(
            self.channel,
            json.dumps(
                {
                    "type": event_alias,
                    "user_id": user_id,
                    "payload": payload,
                }
            ),
        )
        logger.debug(
            "Published event",
            extra={"channel": self.channel, "type": event_alias, "user_id": user_id},
        )
