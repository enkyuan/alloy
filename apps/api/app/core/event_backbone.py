"""Legacy Redis event backbone helper.

This module is intentionally kept for historical reference and is not used by
the active worker/transport pipeline.
"""

import time
import logging
from typing import Optional
from redis.asyncio import Redis
from app.core.config import settings

logger = logging.getLogger(__name__)


class EventBackbone:
    def __init__(self):
        self.redis: Optional[Redis] = None

    async def connect(self):
        if not self.redis:
            logger.info("Connecting to Redis Event Backbone...")
            self.redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            try:
                await self.redis.ping()
                logger.info("Successfully connected to Redis Event Backbone")
            except Exception as e:
                logger.error(f"Failed to connect to Redis Event Backbone: {e}")
                raise e

    async def close(self):
        if self.redis:
            logger.info("Closing Redis Event Backbone connection...")
            await self.redis.close()
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

        stream_key = "stream:voice_input"
        entry = {"user_id": user_id, "text": text, "timestamp": str(time.time())}

        try:
            # XADD returns the ID of the added entry
            message_id = await self.redis.xadd(stream_key, entry)
            logger.info(
                f"Produced voice input to stream {stream_key}: ID={message_id} User={user_id}"
            )
            return message_id
        except Exception as e:
            logger.error(f"Failed to produce voice input to stream {stream_key}: {e}")
            raise e


# Global instance
event_backbone = EventBackbone()
