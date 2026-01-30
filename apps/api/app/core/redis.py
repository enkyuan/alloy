"""
Redis configuration for Agent event backbone.
"""

import logging
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis Client
redis_client: Optional[redis.Redis] = None


async def get_redis_client() -> redis.Redis:
    """Get or create the global Redis client."""
    global redis_client
    if redis_client is None:
        logger.info(f"Connecting to Redis at {settings.REDIS_URL}")
        redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def close_redis_client():
    """Close the global Redis client."""
    global redis_client
    if redis_client:
        logger.info("Closing Redis connection")
        await redis_client.close()
        redis_client = None


class RedisKeys:
    """Central registry of Redis keys and stream names."""

    # Streams
    STREAM_VOICE_INPUT = "stream:voice_input"

    # Consumer Groups
    GROUP_LLM_WORKER = "group:llm_worker"

    # Channels (Pub/Sub)
    CHANNEL_USER_UPDATES = "channel:user_updates"

    @staticmethod
    def conversation_history(conversation_id: str) -> str:
        return f"conversation:{conversation_id}:history"
