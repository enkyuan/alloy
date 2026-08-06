"""Redis-backed conversation history helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from kaji.core.safe_logging import log_redacted_failure

logger = logging.getLogger(__name__)


def history_key(user_id: str) -> str:
    return f"agent:history:{user_id}"


async def append_history(
    redis: Any,
    user_id: str,
    role: str,
    content: str,
    *,
    history_limit: int,
) -> None:
    key = history_key(user_id)
    entry = {"role": role, "content": content}

    last_item = await redis.lindex(key, -1)
    if last_item:
        try:
            if isinstance(last_item, bytes):
                last_item = last_item.decode("utf-8")
            last_entry = json.loads(last_item)
            if (
                isinstance(last_entry, dict)
                and str(last_entry.get("role")) == role
                and str(last_entry.get("content")) == content
            ):
                return
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Skipping invalid history tail entry",
                error,
            )

    await redis.rpush(key, json.dumps(entry))
    if history_limit > 0:
        await redis.ltrim(key, -history_limit, -1)


async def get_history(redis: Any, user_id: str) -> list[dict[str, str]]:
    raw_items = await redis.lrange(history_key(user_id), 0, -1)
    messages: list[dict[str, str]] = []
    for item in raw_items:
        try:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            data = json.loads(item)
            if isinstance(data, dict) and "role" in data and "content" in data:
                messages.append(
                    {"role": str(data["role"]), "content": str(data["content"])}
                )
        except Exception as error:
            log_redacted_failure(
                logger,
                logging.WARNING,
                "Skipping invalid history entry",
                error,
            )
            continue
    return messages
