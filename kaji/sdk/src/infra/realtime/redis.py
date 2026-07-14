"""Redis configuration for the optional realtime event backbone."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kaji.core.config import get_settings

logger = logging.getLogger(__name__)

# Global Redis clients (typed as Any so the type checker is happy when redis is optional)
redis_client: Optional[Any] = None
redis_stream_client: Optional[Any] = None
redis_binary_client: Optional[Any] = None


def _get_redis_module() -> Any:
    """Lazily import redis.asyncio, raising ImportError if not installed."""
    try:
        import redis.asyncio as _redis  # noqa: PLC0415

        return _redis
    except ImportError as exc:
        raise ImportError(
            "Redis is required for realtime features. "
            "Install with: pip install 'kaji-sdk[realtime]'"
        ) from exc


async def get_redis_client() -> Any:
    """Get or create the global Redis client."""
    global redis_client
    if redis_client is None:
        _redis = _get_redis_module()
        settings = get_settings()
        logger.info("Connecting to Redis (endpoint and credentials redacted)")
        redis_client = _redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            encoding_errors="replace",
            decode_responses=True,
        )
    return redis_client


async def get_redis_stream_client() -> Any:
    """Get or create a Redis client for stream consumers with raw byte payloads."""
    global redis_stream_client
    if redis_stream_client is None:
        _redis = _get_redis_module()
        settings = get_settings()
        logger.info(
            "Connecting stream Redis client (endpoint and credentials redacted)"
        )
        redis_stream_client = _redis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
        )
    return redis_stream_client


async def get_redis_binary_client() -> Any:
    """Get or create a Redis client for binary payloads."""
    global redis_binary_client
    if redis_binary_client is None:
        _redis = _get_redis_module()
        settings = get_settings()
        logger.info(
            "Connecting binary Redis client (endpoint and credentials redacted)"
        )
        redis_binary_client = _redis.from_url(
            settings.REDIS_URL,
            decode_responses=False,
        )
    return redis_binary_client


async def close_redis_client() -> None:
    """Close all global Redis clients."""
    global redis_client, redis_stream_client, redis_binary_client
    if redis_client:
        logger.info("Closing Redis connection")
        await redis_client.aclose()
        redis_client = None
    if redis_stream_client:
        logger.info("Closing stream Redis connection")
        await redis_stream_client.aclose()
        redis_stream_client = None
    if redis_binary_client:
        logger.info("Closing binary Redis connection")
        await redis_binary_client.aclose()
        redis_binary_client = None


class RedisKeys:
    """Central registry of every Redis key, stream, group, channel, and
    consumer name used by the Kaji realtime backbone.

    Versioning policy
    -----------------
    All *addressable* keys (streams, groups, channels, outbox queues, dedupe
    prefixes) carry a ``:v1`` version suffix so consumers can be migrated
    without key collisions.

    **Excluded from versioning:**

    * ``CONSUMER_*`` constants — consumer names are per-process identifiers
      (a process-specific suffix is appended at runtime).  They are never used
      as Redis key addresses directly.
    * ``AGENT_CACHE_PREFIX`` — a raw key prefix, not a complete key.  Callers
      append the cache name and version is implicit in the full key they build.
    """

    # Streams
    STREAM_AGENT_INPUT = "stream:agent_input:v1"
    STREAM_TOOL_RESULTS = "stream:tool_results:v1"

    # Consumer Groups
    GROUP_LLM_WORKER = "group:llm_worker:v1"
    GROUP_LLM_WORKER_TOOL_RESULTS = "group:llm_worker_tool_results:v1"

    # Consumer names (a per-process suffix is appended at runtime;
    # these are not Redis addresses so they do not carry :v1)
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
