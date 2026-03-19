"""Tool definitions and handlers for integration commands."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.redis import get_redis_client
from app.services.integrations.dispatcher import (
    ToolContext,
    register_tool,
    tool_spec_from_model,
)
from app.services.integrations.spotify import spotify_service
from app.services.integrations.spotify.helpers.resolver_memory import (
    load_preferred_uris,
    remember_selected_uri,
)
from app.services.todoist import todoist_service


class SpotifyPlayArgs(BaseModel):
    query: str = Field(description="Song name to play.")
    uri: Optional[str] = Field(
        default=None,
        description="Optional direct Spotify URI to play.",
    )
    artist: Optional[str] = Field(default=None, description="Optional artist name.")
    playlist_name: Optional[str] = Field(
        default=None,
        description="Optional playlist name to search first for this track.",
    )


SPOTIFY_PLAY = tool_spec_from_model(
    name="spotify.play",
    description="Play a song, artist, or album on Spotify.",
    model=SpotifyPlayArgs,
)


@register_tool(SPOTIFY_PLAY)
async def spotify_play(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    uri = str(args.get("uri", "")).strip()
    if uri:
        result = await spotify_service.play_track_uri(
            uri=uri,
            access_token=access_token,
        )
        return {
            "status": "playing",
            "message": result.message,
            "query": str(args.get("query", "")).strip() or uri,
            "data": result.data,
        }

    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("Missing required arg: query")
    artist = args.get("artist")
    playlist_name = args.get("playlist_name")
    artist_text = str(artist) if artist else None
    redis = await get_redis_client()
    preferred_uris = await load_preferred_uris(
        redis,
        user_id=ctx.user_id,
        query=query,
        artist=artist_text,
    )
    result = await spotify_service.search_and_play_track(
        query=query,
        access_token=access_token,
        artist=artist_text,
        playlist_name=str(playlist_name) if playlist_name else None,
        preferred_uris=preferred_uris,
        disable_clarifications=settings.SPOTIFY_DISABLE_CLARIFICATION_MESSAGES,
    )
    data = result.data if isinstance(result.data, dict) else {}
    resolved_uri = str(data.get("uri", "")).strip()
    if resolved_uri:
        await remember_selected_uri(
            redis,
            user_id=ctx.user_id,
            query=query,
            artist=artist_text,
            uri=resolved_uri,
        )
    requires_clarification = bool(
        isinstance(result.data, dict) and result.data.get("requires_clarification")
    )
    return {
        "status": "clarification_needed" if requires_clarification else "playing",
        "message": result.message,
        "query": query,
        "data": result.data,
    }


class SpotifyAddToQueueArgs(BaseModel):
    query: str = Field(description="Song name to add to queue.")
    artist: Optional[str] = Field(default=None, description="Optional artist name.")
    playlist_name: Optional[str] = Field(
        default=None,
        description="Optional playlist name to search first for this track.",
    )


SPOTIFY_ADD_TO_QUEUE = tool_spec_from_model(
    name="spotify.add_to_queue",
    description="Add a track to the Spotify playback queue.",
    model=SpotifyAddToQueueArgs,
)


@register_tool(SPOTIFY_ADD_TO_QUEUE)
async def spotify_add_to_queue(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("Missing required arg: query")
    artist = args.get("artist")
    playlist_name = args.get("playlist_name")
    artist_text = str(artist) if artist else None
    redis = await get_redis_client()
    preferred_uris = await load_preferred_uris(
        redis,
        user_id=ctx.user_id,
        query=query,
        artist=artist_text,
    )
    result = await spotify_service.add_to_queue(
        query=query,
        access_token=access_token,
        artist=artist_text,
        playlist_name=str(playlist_name) if playlist_name else None,
        preferred_uris=preferred_uris,
        disable_clarifications=settings.SPOTIFY_DISABLE_CLARIFICATION_MESSAGES,
    )
    data = result.data if isinstance(result.data, dict) else {}
    resolved_uri = str(data.get("uri", "")).strip()
    if resolved_uri:
        await remember_selected_uri(
            redis,
            user_id=ctx.user_id,
            query=query,
            artist=artist_text,
            uri=resolved_uri,
        )
    requires_clarification = bool(
        isinstance(result.data, dict) and result.data.get("requires_clarification")
    )
    return {
        "status": "clarification_needed" if requires_clarification else "queued",
        "message": result.message,
        "query": query,
        "data": result.data,
    }


class SpotifyPlayAlbumArgs(BaseModel):
    album: str = Field(description="Album name to play.")
    artist: Optional[str] = Field(default=None, description="Optional artist name.")


SPOTIFY_PLAY_ALBUM = tool_spec_from_model(
    name="spotify.play_album",
    description="Play an album on Spotify.",
    model=SpotifyPlayAlbumArgs,
)


@register_tool(SPOTIFY_PLAY_ALBUM)
async def spotify_play_album(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    album = str(args.get("album", "")).strip()
    if not album:
        raise ValueError("Missing required arg: album")
    artist = args.get("artist")
    result = await spotify_service.search_and_play_album(
        query=album, access_token=access_token, artist=str(artist) if artist else None
    )
    return {
        "status": "playing",
        "message": result.message,
        "album": album,
        "data": result.data,
    }


class SpotifyPlayPlaylistArgs(BaseModel):
    playlist: str = Field(description="Playlist name to play.")
    user_playlists_only: Optional[bool] = Field(
        default=False, description="Only search the user's playlists."
    )


SPOTIFY_PLAY_PLAYLIST = tool_spec_from_model(
    name="spotify.play_playlist",
    description="Play a playlist on Spotify.",
    model=SpotifyPlayPlaylistArgs,
)


@register_tool(SPOTIFY_PLAY_PLAYLIST)
async def spotify_play_playlist(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    playlist = str(args.get("playlist", "")).strip()
    if not playlist:
        raise ValueError("Missing required arg: playlist")
    user_only = bool(args.get("user_playlists_only", False))
    result = await spotify_service.search_and_play_playlist(
        query=playlist,
        access_token=access_token,
        user_playlists_only=user_only,
        disable_clarifications=settings.SPOTIFY_DISABLE_CLARIFICATION_MESSAGES,
    )
    return {
        "status": "playing",
        "message": result.message,
        "playlist": playlist,
        "data": result.data,
    }


class SpotifyPauseArgs(BaseModel):
    pass


SPOTIFY_PAUSE = tool_spec_from_model(
    name="spotify.pause",
    description="Pause Spotify playback.",
    model=SpotifyPauseArgs,
)


@register_tool(SPOTIFY_PAUSE)
async def spotify_pause(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    result = await spotify_service.pause_playback(access_token)
    return {"status": "paused", "message": result.message, "data": result.data}


class SpotifyNextArgs(BaseModel):
    pass


SPOTIFY_NEXT = tool_spec_from_model(
    name="spotify.next",
    description="Skip to the next song on Spotify.",
    model=SpotifyNextArgs,
)


@register_tool(SPOTIFY_NEXT)
async def spotify_next(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    result = await spotify_service.next_track(access_token)
    return {"status": "skipped", "message": result.message, "data": result.data}


class SpotifyPreviousArgs(BaseModel):
    pass


SPOTIFY_PREVIOUS = tool_spec_from_model(
    name="spotify.previous",
    description="Skip to the previous song on Spotify.",
    model=SpotifyPreviousArgs,
)


@register_tool(SPOTIFY_PREVIOUS)
async def spotify_previous(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    result = await spotify_service.previous_track(access_token)
    return {
        "status": "skipped_previous",
        "message": result.message,
        "data": result.data,
    }


class SpotifyResumeArgs(BaseModel):
    pass


SPOTIFY_RESUME = tool_spec_from_model(
    name="spotify.resume",
    description="Resume Spotify playback.",
    model=SpotifyResumeArgs,
)


@register_tool(SPOTIFY_RESUME)
async def spotify_resume(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    result = await spotify_service.resume_playback(access_token)
    return {"status": "resumed", "message": result.message, "data": result.data}


class SpotifySetVolumeArgs(BaseModel):
    level: int = Field(description="Volume level (0-100).")


SPOTIFY_SET_VOLUME = tool_spec_from_model(
    name="spotify.set_volume",
    description="Set Spotify playback volume.",
    model=SpotifySetVolumeArgs,
)


@register_tool(SPOTIFY_SET_VOLUME)
async def spotify_set_volume(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    level = args.get("level")
    if level is None:
        raise ValueError("Missing required arg: level")
    result = await spotify_service.set_volume(access_token, int(level))
    return {"status": "volume_set", "message": result.message, "data": result.data}


class SpotifyListDevicesArgs(BaseModel):
    pass


SPOTIFY_LIST_DEVICES = tool_spec_from_model(
    name="spotify.list_devices",
    description="List available Spotify playback devices.",
    model=SpotifyListDevicesArgs,
)


@register_tool(SPOTIFY_LIST_DEVICES)
async def spotify_list_devices(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    result = await spotify_service.get_available_devices(access_token)
    return {"status": "devices", "message": result.message, "data": result.data}


class SpotifySwitchDeviceArgs(BaseModel):
    device_name: Optional[str] = Field(default=None, description="Name of device.")
    device_id: Optional[str] = Field(default=None, description="Device ID.")


SPOTIFY_SWITCH_DEVICE = tool_spec_from_model(
    name="spotify.switch_device",
    description="Switch Spotify playback to a device.",
    model=SpotifySwitchDeviceArgs,
)


@register_tool(SPOTIFY_SWITCH_DEVICE)
async def spotify_switch_device(
    ctx: ToolContext, args: Dict[str, Any]
) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    device_name = args.get("device_name")
    device_id = args.get("device_id")
    result = await spotify_service.switch_device(
        access_token,
        device_name=str(device_name) if device_name else None,
        device_id=str(device_id) if device_id else None,
    )
    return {"status": "switched", "message": result.message, "data": result.data}


class TodoistCreateTaskArgs(BaseModel):
    content: str = Field(description="Task title/content.")
    project_id: Optional[str] = Field(default=None, description="Optional project ID.")
    due_string: Optional[str] = Field(
        default=None, description="Optional due date in natural language."
    )


TODOIST_CREATE_TASK = tool_spec_from_model(
    name="todoist.create_task",
    description="Create a task in Todoist.",
    model=TodoistCreateTaskArgs,
)


@register_tool(TODOIST_CREATE_TASK)
async def todoist_create_task(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await todoist_service.get_valid_token(ctx.integration, ctx.db)
    content = str(args.get("content", "")).strip()
    if not content:
        raise ValueError("Missing required arg: content")
    project_id = args.get("project_id")
    due_string = args.get("due_string")
    result = await todoist_service.create_task(
        access_token=access_token,
        content=content,
        project_id=str(project_id) if project_id else None,
        due_string=str(due_string) if due_string else None,
    )
    return {"status": "created", "task": result}
