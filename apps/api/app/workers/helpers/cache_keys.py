"""Cache key helpers used by the LLM worker."""

import hashlib
import json
import re
from typing import Any


def response_cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"agent:cache:{digest}"


def cache_hit_key() -> str:
    return "agent:cache:hit"


def cache_miss_key() -> str:
    return "agent:cache:miss"


def normalize_spotify_query(query: str, artist: str | None = None) -> str:
    text = f"{query} {artist or ''}".lower()
    text = re.sub(r"\b(on|in|with)\s+spotify\b", "", text)
    text = re.sub(r"\bspotify\b", "", text)
    text = re.sub(
        r"\b(play|please|could you|can you|would you|hey|hi|haven)\b", "", text
    )
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def spotify_cache_key(query: str, artist: str | None = None) -> str:
    normalized = normalize_spotify_query(query, artist)
    return f"spotify:cache:track:{normalized}"
