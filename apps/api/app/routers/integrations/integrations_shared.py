"""Shared dependencies for integration router modules."""

import redis.asyncio as redis

from app.core.config import settings

# OAuth state TTL in seconds (15 minutes)
OAUTH_STATE_TTL = 900

# Redis client used to persist OAuth state between auth and code exchange callbacks.
redis_client = redis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)
