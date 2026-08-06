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
            "Install with: pip install 'kaji-sdk[realtime]==0.2.0b1'"
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
