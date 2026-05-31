"""
Redis configuration for Agent event backbone.
"""

import logging
from typing import Optional

import redis.asyncio as redis

from agentkit.core.config import settings

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
    """Central registry of every Redis key, stream, group, channel, and
    consumer name. All values follow the ``namespace:purpose:v1`` scheme so
    they can be versioned together.
    """

    # Streams
    STREAM_AGENT_INPUT = "stream:agent_input:v1"
    STREAM_TOOL_RESULTS = "stream:tool_results:v1"

    # Consumer Groups
    GROUP_LLM_WORKER = "group:llm_worker:v1"
    GROUP_LLM_WORKER_TOOL_RESULTS = "group:llm_worker_tool_results:v1"

    # Consumer names (a per-process suffix is appended at runtime)
    CONSUMER_LLM_WORKER = "llm_worker"
    CONSUMER_TOOL_RESULTS_WORKER = "llm_tool_results_worker"

    # Channels (Pub/Sub)
    CHANNEL_USER_UPDATES = "channel:user_updates:v1"

    # Agent Cache
    AGENT_CACHE_PREFIX = "agent:cache:"
    AGENT_CACHE_HIT = "agent:cache:hit:v1"
    AGENT_CACHE_MISS = "agent:cache:miss:v1"

    # Outbox (reliable user-update delivery)
    USER_UPDATE_OUTBOX_KEY = "outbox:user_updates:v1"
    USER_UPDATE_OUTBOX_DLQ_KEY = "dlq:user_updates:v1"

    # Dead-letter queues
    TOOL_RESULT_DLQ_KEY = "dlq:tool_results:v1"
    TOOL_RESULT_DLQ_DEAD_KEY = "dlq:tool_results:dead:v1"
    VOICE_INPUT_DLQ_KEY = "dlq:voice_input:v1"
    VOICE_INPUT_DLQ_DEAD_KEY = "dlq:voice_input:dead:v1"

    # Dedupe prefixes
    TOOL_RESULT_SEEN_KEY_PREFIX = "tool_result:seen:v1:"
    TOOL_CALL_DEDUP_IN_PROGRESS_PREFIX = "tool_call:inflight:v1:"
    TOOL_CALL_DEDUP_DONE_PREFIX = "tool_call:done:v1:"

    @staticmethod
    def conversation_history(conversation_id: str) -> str:
        return f"conversation:{conversation_id}:history:v1"


class RedisConfig:
    """Tuning constants (TTLs, max lengths, retry budgets) for Redis-backed
    queues and dedupe. Separate from :class:`RedisKeys`, which holds names.
    """

    # Tool result publishing
    TOOL_RESULT_PUBLISH_MAX_ATTEMPTS = 3
    TOOL_RESULT_PUBLISH_BASE_RETRY_DELAY_SECONDS = 0.25
    TOOL_RESULT_STREAM_MAXLEN = 10_000

    # User-update outbox
    USER_UPDATE_OUTBOX_MAXLEN = 2_000
    USER_UPDATE_OUTBOX_MAX_DRAIN = 100
    USER_UPDATE_OUTBOX_TTL_SECONDS = 24 * 60 * 60
    USER_UPDATE_OUTBOX_DLQ_MAXLEN = 2_000
    USER_UPDATE_OUTBOX_DLQ_TTL_SECONDS = 7 * 24 * 60 * 60

    # Tool result DLQ
    TOOL_RESULT_DLQ_MAXLEN = 2_000
    TOOL_RESULT_DLQ_MAX_DRAIN = 25
    TOOL_RESULT_DLQ_MAX_RETRIES = 3
    TOOL_RESULT_DLQ_TTL_SECONDS = 24 * 60 * 60
    TOOL_RESULT_DLQ_DEAD_TTL_SECONDS = 7 * 24 * 60 * 60

    # Voice input DLQ
    VOICE_INPUT_DLQ_MAXLEN = 2_000
    VOICE_INPUT_DLQ_MAX_DRAIN = 25
    VOICE_INPUT_DLQ_MAX_RETRIES = 3
    VOICE_INPUT_DLQ_TTL_SECONDS = 24 * 60 * 60
    VOICE_INPUT_DLQ_DEAD_TTL_SECONDS = 7 * 24 * 60 * 60

    # Dedupe TTLs
    TOOL_RESULT_SEEN_TTL_SECONDS = 24 * 60 * 60
    TOOL_CALL_DEDUP_TTL_SECONDS = 24 * 60 * 60
    TOOL_CALL_DEDUP_IN_PROGRESS_TTL_SECONDS = 5 * 60

    # Tool exec
    TOOL_CALL_RETRYABLE_TOOL_NAMES: frozenset[str] = frozenset()
