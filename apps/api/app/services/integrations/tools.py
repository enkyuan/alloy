"""Tool definitions and handlers for integration commands."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.services.integrations.dispatcher import (
    ToolContext,
    register_tool,
    tool_spec_from_model,
)
from app.services.spotify import spotify_service
from app.services.todoist import todoist_service


class SpotifyPlayArgs(BaseModel):
    query: str = Field(
        description="Song, artist, album, or playlist name to play."
    )


SPOTIFY_PLAY = tool_spec_from_model(
    name="spotify.play",
    description="Play a song, artist, or album on Spotify.",
    model=SpotifyPlayArgs,
)


@register_tool(SPOTIFY_PLAY)
async def spotify_play(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    access_token = await spotify_service.get_valid_token(ctx.integration, ctx.db)
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("Missing required arg: query")
    result = await spotify_service.search_and_play_track(
        query=query, access_token=access_token
    )
    return {"status": "playing", "query": query, "data": result.data}


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
    return {"status": "paused", "data": result.data}


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
