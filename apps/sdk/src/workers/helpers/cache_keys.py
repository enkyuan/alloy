"""Cache key helpers used by the LLM worker."""

import hashlib
import json
from typing import Any


def response_cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"agent:cache:{digest}"


def cache_hit_key() -> str:
    return "agent:cache:hit"


def cache_miss_key() -> str:
    return "agent:cache:miss"
