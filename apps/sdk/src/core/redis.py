"""
Redis configuration for Agent event backbone.
"""

import logging
from typing import Optional

import redis.asyncio as redis

from src.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis Client
redis_client: Optional[redis.Redis] = None
redis_stream_client: Optional[redis.Redis] = None


async def get_redis_client() -> redis.Redis:
    """Get or create the global Redis client."""
    global redis_client
    if redis_client is None:
        logger.info("Connecting to Redis at %s", settings.REDIS_URL)
        redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            encoding_errors="replace",
            decode_responses=True,
        )
    return redis_client


async def get_redis_stream_client() -> redis.Redis:
    """Get or create a Redis client for stream consumers with raw byte payloads."""
    global redis_stream_client
    if redis_stream_client is None:
        logger.info("Connecting stream Redis client at %s", settings.REDIS_URL)
        redis_stream_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
        )
    return redis_stream_client


async def close_redis_client():
    """Close the global Redis client."""
    global redis_client, redis_stream_client
    if redis_client:
        logger.info("Closing Redis connection")
        await redis_client.close()
        redis_client = None
    if redis_stream_client:
        logger.info("Closing stream Redis connection")
        await redis_stream_client.close()
        redis_stream_client = None


class RedisKeys:
    """Central registry of Redis keys and stream names."""

    # Streams
    STREAM_VOICE_INPUT = "stream:voice_input"
    STREAM_TOOL_RESULTS = "stream:tool_results"

    # Consumer Groups
    GROUP_LLM_WORKER = "group:llm_worker"
    GROUP_LLM_WORKER_TOOL_RESULTS = "group:llm_worker_tool_results"

    # Channels (Pub/Sub)
    CHANNEL_USER_UPDATES = "channel:user_updates"

    # Agent Cache
    AGENT_CACHE_PREFIX = "agent:cache:"
    AGENT_CACHE_HIT = "agent:cache:hit"
    AGENT_CACHE_MISS = "agent:cache:miss"

    @staticmethod
    def conversation_history(conversation_id: str) -> str:
        return f"conversation:{conversation_id}:history"
