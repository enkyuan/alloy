"""
Redis and event helper functions for the LLM worker.
"""

import json
import logging
import uuid
from typing import Any

from app.core.events import AgentResponse, ToolCall, ToolResult, build_event_envelope
from app.core.redis import RedisKeys
from app.workers.helpers.cache_keys import spotify_cache_key

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
    entry = {"role": role, "content": content}
    await redis.rpush(history_key(user_id), json.dumps(entry))
    if history_limit > 0:
        await redis.ltrim(history_key(user_id), -history_limit, -1)


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
        except Exception:
            logger.warning("Skipping invalid history entry", exc_info=True)
            continue
    return messages


async def publish_user_update(
    redis: Any,
    *,
    event_type: str,
    user_id: str,
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    envelope = build_event_envelope(
        event_type=event_type,
        user_id=user_id,
        payload=payload,
        metadata=metadata or {},
    )
    await redis.publish(RedisKeys.CHANNEL_USER_UPDATES, json.dumps(envelope))


async def cache_spotify_result(
    redis: Any,
    tool_result: ToolResult,
    *,
    spotify_cache_ttl_seconds: int,
) -> None:
    if tool_result.tool_name != "spotify.play":
        return
    if not isinstance(tool_result.result, dict):
        return
    data = tool_result.result.get("data")
    if not isinstance(data, dict):
        return

    uri = data.get("uri")
    track_name = data.get("track_name")
    artist = data.get("artist")
    if not uri or not track_name:
        return

    query = tool_result.tool_args.get("query") if tool_result.tool_args else None
    if not query:
        query = track_name

    cache_key = spotify_cache_key(str(query), str(artist) if artist else None)
    payload = {
        "uri": uri,
        "track_name": track_name,
        "artist": artist,
    }
    await redis.setex(cache_key, spotify_cache_ttl_seconds, json.dumps(payload))
    logger.info(
        "Cached Spotify play result",
        extra={
            "cache_key": cache_key,
            "track_name": str(track_name),
            "artist": str(artist) if artist else "",
        },
    )


async def try_cached_spotify_play(
    redis: Any,
    user_id: str,
    tool_args: dict[str, Any],
    *,
    history_limit: int,
) -> bool:
    query = str(tool_args.get("query", "")).strip()
    if not query:
        return False

    artist = tool_args.get("artist")
    cache_key = spotify_cache_key(query, str(artist) if artist else None)
    cached = await redis.get(cache_key)
    if not cached:
        logger.debug(
            "No cached Spotify track for query",
            extra={"user_id": user_id, "query": query, "cache_key": cache_key},
        )
        return False

    try:
        payload = json.loads(cached)
    except Exception:
        logger.warning(
            "Invalid cached Spotify payload",
            extra={"user_id": user_id, "cache_key": cache_key},
            exc_info=True,
        )
        return False

    uri = payload.get("uri")
    if not uri:
        return False

    tool_call_id = str(uuid.uuid4())
    tool_call_event = ToolCall(
        tool_name="spotify.play",
        tool_args={"uri": uri},
        tool_call_id=tool_call_id,
    )
    await publish_user_update(
        redis,
        event_type="tool.call",
        user_id=user_id,
        payload=tool_call_event,
        metadata={"source": "llm_worker.cached_spotify_play"},
    )

    track_name = payload.get("track_name")
    artist_name = payload.get("artist")
    if track_name and artist_name:
        response_text = f"Playing {track_name} by {artist_name}."
    elif track_name:
        response_text = f"Playing {track_name}."
    else:
        response_text = "Playing on Spotify."

    await append_history(
        redis,
        user_id,
        "assistant",
        response_text,
        history_limit=history_limit,
    )
    response_event = AgentResponse(content=response_text)
    await publish_user_update(
        redis,
        event_type="agent.response",
        user_id=user_id,
        payload=response_event,
        metadata={"source": "llm_worker.cached_spotify_play"},
    )
    logger.info(
        "Served Spotify play request from cache",
        extra={"user_id": user_id, "query": query, "cache_key": cache_key},
    )
    return True
