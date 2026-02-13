"""Stateful Spotify clarification transaction helpers."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.core.events import ToolResult

logger = logging.getLogger(__name__)

SPOTIFY_CLARIFICATION_TTL_SECONDS = 150


def spotify_clarification_key(user_id: str) -> str:
    return f"agent:spotify:clarification:{user_id}"


@dataclass(frozen=True)
class SpotifyClarificationResolution:
    """Resolution result for a pending Spotify clarification transaction."""

    action: Literal["play_uri", "respond", "bypass"]
    tool_args: dict[str, Any] | None = None
    response_text: str | None = None


def _normalize_text(value: str) -> str:
    normalized = value.lower().strip()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _extract_numeric_selection(text: str, option_count: int) -> Optional[int]:
    if option_count <= 0:
        return None

    numeric_match = re.search(r"\b([1-9])\b", text)
    if numeric_match:
        selected = int(numeric_match.group(1))
        if 1 <= selected <= option_count:
            return selected - 1

    ordinal_map = {
        "first": 0,
        "second": 1,
        "third": 2,
    }
    for ordinal, index in ordinal_map.items():
        if re.search(rf"\b{ordinal}\b", text) and index < option_count:
            return index
    return None


def _select_option_by_content(
    user_text: str,
    options: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    normalized_user_text = _normalize_text(user_text)
    if not normalized_user_text or not options:
        return None

    selected_index = _extract_numeric_selection(normalized_user_text, len(options))
    if selected_index is not None:
        return options[selected_index]

    best_option: Optional[dict[str, Any]] = None
    best_score = 0.0
    second_score = 0.0
    for option in options:
        track_name = _normalize_text(str(option.get("track_name", "")))
        artist_name = _normalize_text(str(option.get("artist", "")))
        label = _normalize_text(str(option.get("label", "")))

        score = 0.0
        if track_name and track_name in normalized_user_text:
            score += 0.52
        if artist_name and artist_name in normalized_user_text:
            score += 0.33
        score += _token_overlap(normalized_user_text, label) * 0.50
        score += _token_overlap(normalized_user_text, track_name) * 0.35
        score += _token_overlap(normalized_user_text, artist_name) * 0.20

        if score > best_score:
            second_score = best_score
            best_score = score
            best_option = option
        elif score > second_score:
            second_score = score

    if best_option and best_score >= 0.58 and (best_score - second_score) >= 0.08:
        return best_option
    return None


def _is_explicit_new_command(user_text: str) -> bool:
    normalized = _normalize_text(user_text)
    if not normalized:
        return False
    return bool(
        re.search(
            (
                r"\b(play|pause|resume|next|previous|queue|add|switch|device|"
                r"volume|album|playlist)\b"
            ),
            normalized,
        )
    )


def _build_reminder_text(state: dict[str, Any]) -> str:
    options = state.get("options")
    if not isinstance(options, list) or not options:
        return "Please pick one of the listed options."

    numbered_options: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("id", "")).strip()
        label = str(option.get("label", "")).strip()
        if option_id and label:
            numbered_options.append(f"{option_id}) {label}")

    options_text = " ".join(numbered_options)
    if not options_text:
        return "Please pick one of the listed options."
    return (
        "I still need a specific choice. Reply with the option number or artist name. "
        f"{options_text}"
    )


def _sanitize_option_item(raw_option: Any, index: int) -> Optional[dict[str, Any]]:
    if not isinstance(raw_option, dict):
        return None

    uri = str(raw_option.get("uri", "")).strip()
    if not uri:
        return None

    track_name = str(raw_option.get("track_name", "")).strip()
    artist = str(raw_option.get("artist", "")).strip()
    label = str(raw_option.get("label", "")).strip()
    if not label:
        if track_name and artist:
            label = f"{track_name} by {artist}"
        elif track_name:
            label = track_name
        else:
            label = uri

    option_id = str(raw_option.get("id", "")).strip() or str(index)
    return {
        "id": option_id,
        "uri": uri,
        "track_name": track_name,
        "artist": artist,
        "label": label,
    }


def _build_clarification_state(tool_result: ToolResult) -> Optional[dict[str, Any]]:
    if tool_result.tool_name not in {"spotify.play", "spotify.add_to_queue"}:
        return None
    if not isinstance(tool_result.result, dict):
        return None

    result = tool_result.result
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    if not data.get("requires_clarification"):
        return None

    raw_option_items = data.get("option_items")
    if not isinstance(raw_option_items, list):
        return None

    option_items: list[dict[str, Any]] = []
    for index, raw_option in enumerate(raw_option_items, start=1):
        sanitized = _sanitize_option_item(raw_option, index=index)
        if sanitized:
            option_items.append(sanitized)

    if not option_items:
        return None

    message = result.get("message")
    query = data.get("query")
    artist = data.get("artist")
    playlist_name = data.get("playlist_name")
    clarification_id = str(data.get("clarification_id", "")).strip() or str(
        uuid.uuid4()
    )

    return {
        "clarification_id": clarification_id,
        "tool_name": tool_result.tool_name,
        "query": str(query or ""),
        "artist": str(artist or ""),
        "playlist_name": str(playlist_name or ""),
        "message": str(message or ""),
        "options": option_items,
        "attempts": 0,
    }


async def cache_spotify_clarification(
    redis: Any,
    *,
    user_id: str,
    tool_result: ToolResult,
    ttl_seconds: int = SPOTIFY_CLARIFICATION_TTL_SECONDS,
) -> None:
    """Persist or clear pending Spotify clarification state for a user."""
    if tool_result.tool_name not in {"spotify.play", "spotify.add_to_queue"}:
        return

    state = _build_clarification_state(tool_result)
    key = spotify_clarification_key(user_id)

    if not state:
        await redis.delete(key)
        return

    await redis.setex(key, ttl_seconds, json.dumps(state))
    logger.info(
        "Cached spotify clarification transaction",
        extra={
            "user_id": user_id,
            "clarification_id": state.get("clarification_id"),
            "options_count": len(state.get("options", [])),
        },
    )


async def get_spotify_clarification_state(
    redis: Any, user_id: str
) -> Optional[dict[str, Any]]:
    raw = await redis.get(spotify_clarification_key(user_id))
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        logger.warning(
            "Invalid spotify clarification state payload",
            extra={"user_id": user_id},
            exc_info=True,
        )
        return None
    return parsed if isinstance(parsed, dict) else None


async def clear_spotify_clarification_state(redis: Any, user_id: str) -> None:
    await redis.delete(spotify_clarification_key(user_id))


async def resolve_spotify_clarification(
    redis: Any,
    *,
    user_id: str,
    user_text: str,
    ttl_seconds: int = SPOTIFY_CLARIFICATION_TTL_SECONDS,
) -> Optional[SpotifyClarificationResolution]:
    """Resolve a user reply against pending clarification candidates."""
    state = await get_spotify_clarification_state(redis, user_id)
    if not state:
        return None

    raw_options = state.get("options")
    if not isinstance(raw_options, list):
        await clear_spotify_clarification_state(redis, user_id)
        return None

    option_list = [item for item in raw_options if isinstance(item, dict)]
    if not option_list:
        await clear_spotify_clarification_state(redis, user_id)
        return None

    selected_option = _select_option_by_content(user_text, option_list)
    if selected_option:
        uri = str(selected_option.get("uri", "")).strip()
        if uri:
            return SpotifyClarificationResolution(
                action="play_uri",
                tool_args={"uri": uri},
            )

    if _is_explicit_new_command(user_text):
        await clear_spotify_clarification_state(redis, user_id)
        return SpotifyClarificationResolution(action="bypass")

    attempts = int(state.get("attempts", 0)) + 1
    state["attempts"] = attempts
    await redis.setex(spotify_clarification_key(user_id), ttl_seconds, json.dumps(state))
    return SpotifyClarificationResolution(
        action="respond",
        response_text=_build_reminder_text(state),
    )
