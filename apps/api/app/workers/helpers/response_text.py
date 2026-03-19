"""Helpers for formatting user-facing responses from tool results."""

from __future__ import annotations

from typing import Callable

from app.core.events import ToolResult

ToolFormatter = Callable[[ToolResult, dict[str, object], dict[str, object]], str | None]


def _format_spotify_response(
    tool_result: ToolResult, result: dict[str, object], data: dict[str, object]
) -> str | None:
    message = result.get("message")
    if data.get("requires_clarification") and isinstance(message, str):
        return message

    if isinstance(message, str) and message.strip():
        return message

    if tool_result.tool_name in {
        "spotify.play",
        "spotify.play_album",
        "spotify.play_playlist",
        "spotify.add_to_queue",
    }:
        track_name = (
            data.get("track_name")
            or result.get("query")
            or result.get("album")
            or result.get("playlist")
        )
        artist = data.get("artist")
        if tool_result.tool_name == "spotify.add_to_queue":
            if track_name and artist:
                return f"Added {track_name} by {artist} to your queue."
            if track_name:
                return f"Added {track_name} to your queue."
            return "Added to your queue."
        if track_name and artist:
            return f"Playing {track_name} by {artist}."
        if track_name:
            return f"Playing {track_name}."
        return "Playing on Spotify."

    if tool_result.tool_name == "spotify.pause":
        return "Paused."
    if tool_result.tool_name == "spotify.resume":
        return "Resuming playback."
    if tool_result.tool_name == "spotify.next":
        if data.get("verified") is False:
            return "I sent next, but I could not confirm playback changed."
        return "Skipping to the next track."
    if tool_result.tool_name == "spotify.previous":
        if data.get("verified") is False:
            return "I sent previous, but I could not confirm playback changed."
        return "Going back to the previous track."
    if tool_result.tool_name == "spotify.set_volume":
        level = result.get("volume") or data.get("volume") or data.get("level")
        if isinstance(level, int):
            return f"Volume set to {level}%."
        return "Volume updated."
    if tool_result.tool_name == "spotify.list_devices":
        devices = data.get("devices")
        if isinstance(devices, list):
            return f"Found {len(devices)} devices."
        return "Here are your available devices."
    return None


FORMATTERS_BY_PREFIX: dict[str, ToolFormatter] = {
    "spotify.": _format_spotify_response,
}


def format_response_text(tool_result: ToolResult) -> str:
    """Convert a tool result into a concise assistant response string."""
    if tool_result.error:
        return f"Sorry, I couldn't complete that. {tool_result.error}"

    result_value = tool_result.result
    if result_value is None:
        return "Done."
    if not isinstance(result_value, dict):
        return "Done."
    result: dict[str, object] = result_value

    raw_data = result.get("data")
    data: dict[str, object] = raw_data if isinstance(raw_data, dict) else {}

    for prefix, formatter in FORMATTERS_BY_PREFIX.items():
        if tool_result.tool_name.startswith(prefix):
            formatted = formatter(tool_result, result, data)
            if formatted:
                return formatted
            break

    status = result.get("status")
    if isinstance(status, str) and status:
        return status

    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return message

    return "Done."
