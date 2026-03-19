"""Redis-backed memory helpers for Spotify query disambiguation."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _normalize_for_key(value: str) -> str:
    normalized = value.lower().strip()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _resolver_memory_key(user_id: str, query: str, artist: str | None) -> str:
    normalized_query = _normalize_for_key(query)
    normalized_artist = _normalize_for_key(artist or "")
    return f"agent:spotify:resolver:v1:{user_id}:{normalized_query}:{normalized_artist}"


async def load_preferred_uris(
    redis: Any,
    *,
    user_id: str,
    query: str,
    artist: str | None = None,
    limit: int | None = None,
) -> list[str]:
    """Return user-specific preferred URIs for a normalized query context."""
    max_items = limit or settings.SPOTIFY_RESOLVER_MEMORY_MAX_URIS
    key = _resolver_memory_key(user_id, query, artist)
    try:
        raw_items = await redis.zrevrange(key, 0, max_items - 1)
    except Exception:
        logger.warning(
            "Failed to load Spotify resolver memory",
            extra={"user_id": user_id, "query": query, "key": key},
            exc_info=True,
        )
        return []

    preferred: list[str] = []
    for item in raw_items:
        uri = str(item).strip()
        if uri:
            preferred.append(uri)
    return preferred


async def remember_selected_uri(
    redis: Any,
    *,
    user_id: str,
    query: str,
    uri: str,
    artist: str | None = None,
    ttl_seconds: int | None = None,
) -> None:
    """Record a successful URI pick for future disambiguation."""
    normalized_uri = str(uri).strip()
    if not normalized_uri:
        return

    key = _resolver_memory_key(user_id, query, artist)
    ttl = ttl_seconds or settings.SPOTIFY_RESOLVER_MEMORY_TTL_SECONDS
    try:
        await redis.zincrby(key, 1.0, normalized_uri)
        if ttl > 0:
            await redis.expire(key, ttl)
    except Exception:
        logger.warning(
            "Failed to persist Spotify resolver memory",
            extra={"user_id": user_id, "query": query, "key": key},
            exc_info=True,
        )
