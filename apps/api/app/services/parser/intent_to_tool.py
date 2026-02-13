"""Shared parser-intent to tool-call argument mapping."""

from typing import Any

from app.services.parser.models import CommandIntent


def map_intent_to_tool_call(intent: CommandIntent) -> tuple[str, dict[str, Any]] | None:
    """Convert a parsed command intent into a tool name and args payload."""
    params = intent.parameters or {}

    if intent.intent == "play_track_from_playlist":
        track = params.get("track")
        playlist = params.get("playlist")
        if not track or not playlist:
            return None
        artist = params.get("artist")
        play_from_playlist_args: dict[str, Any] = {
            "query": str(track),
            "playlist_name": str(playlist),
        }
        if artist:
            play_from_playlist_args["artist"] = str(artist)
        return "spotify.play", play_from_playlist_args

    if intent.intent == "play_track":
        track = params.get("track")
        if not track:
            return None
        artist = params.get("artist")
        play_track_args: dict[str, Any] = {"query": str(track)}
        if artist:
            play_track_args["artist"] = str(artist)
        return "spotify.play", play_track_args

    if intent.intent == "play_album":
        album = params.get("album")
        if not album:
            return None
        play_album_args: dict[str, Any] = {"album": album}
        if params.get("artist"):
            play_album_args["artist"] = params["artist"]
        return "spotify.play_album", play_album_args

    if intent.intent == "play_playlist":
        playlist = params.get("playlist")
        if not playlist:
            return None
        raw_text = (intent.raw_text or "").lower()
        user_only = (
            "my playlist" in raw_text
            or "my playlists" in raw_text
            or str(playlist).lower() in {"liked songs", "favorites"}
        )
        return "spotify.play_playlist", {
            "playlist": playlist,
            "user_playlists_only": user_only,
        }

    if intent.intent == "add_to_queue":
        track = params.get("track")
        if not track:
            return None
        artist = params.get("artist")
        queue_args = {"query": str(track)}
        if artist:
            queue_args["artist"] = str(artist)
        if params.get("playlist"):
            queue_args["playlist_name"] = str(params["playlist"])
        return "spotify.add_to_queue", queue_args

    if intent.intent == "pause":
        return "spotify.pause", {}

    if intent.intent == "resume":
        return "spotify.resume", {}

    if intent.intent == "next":
        return "spotify.next", {}

    if intent.intent == "previous":
        return "spotify.previous", {}

    if intent.intent == "set_volume":
        level = params.get("level")
        if level is None:
            return None
        return "spotify.set_volume", {"level": level}

    if intent.intent == "list_devices":
        return "spotify.list_devices", {}

    if intent.intent == "switch_device":
        device = params.get("device")
        if not device:
            return None
        return "spotify.switch_device", {"device_name": device}

    return None
