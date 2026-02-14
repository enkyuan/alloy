import time
import logging
from typing import Optional, Any, cast

from app.core.events import (
    UserTranscriptionReceived,
    build_event_envelope,
    to_redis_stream_fields,
)
from app.core.redis import RedisKeys, close_redis_client, get_redis_client
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class EventBackbone:
    def __init__(self):
        self.redis: Optional[Redis] = None

    async def connect(self):
        if not self.redis:
            logger.info("Connecting to Redis Event Backbone...")
            self.redis = await get_redis_client()
            try:
                await self.redis.ping()
                logger.info("Successfully connected to Redis Event Backbone")
            except Exception as e:
                logger.error("Failed to connect to Redis Event Backbone: %s", e)
                raise

    async def close(self):
        if self.redis:
            logger.info("Closing Redis Event Backbone connection...")
            await close_redis_client()
            self.redis = None

    async def produce_voice_input(self, user_id: str, text: str) -> str:
        """
        Produces a voice input event to the Redis Stream.

        Args:
            user_id: The ID of the user.
            text: The text input from STT.

        Returns:
            The ID of the added message in the stream.
        """
        if not self.redis:
            await self.connect()
        assert self.redis is not None

        stream_key = RedisKeys.STREAM_VOICE_INPUT
        event = UserTranscriptionReceived(content=text, user_id=user_id)
        entry = build_event_envelope(
            event_type="user.transcription",
            user_id=user_id,
            payload=event,
            metadata={"timestamp": str(time.time()), "source": "core.foundation"},
        )

        try:
            # XADD returns the ID of the added entry
            stream_fields = to_redis_stream_fields(entry)
            message_id = await self.redis.xadd(
                stream_key, cast(dict[Any, Any], stream_fields)
            )
            logger.info(
                "Produced voice input to stream %s: ID=%s User=%s",
                stream_key, message_id, user_id,
            )
            return message_id
        except Exception as e:
            logger.error("Failed to produce voice input to stream %s: %s", stream_key, e)
            raise


# Global instance
event_backbone = EventBackbone()
