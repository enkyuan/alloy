"""Google Calendar integration -- read-only via OAuth 2.0.

Installed by `agentkit add gcal`. See SETUP.md (next to this file) for
the Google Cloud OAuth client step. Reads the same env vars as the
Gmail integration (``GOOGLE_OAUTH_CLIENT_ID`` /
``GOOGLE_OAUTH_CLIENT_SECRET``) since both use Google's installed-app
OAuth flow.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

import agentkit
from agentkit.integrations.oauth import GoogleOAuthClient


CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)


class ListEventsArgs(BaseModel):
    calendar_id: str = Field(
        default="primary",
        description="Calendar id; 'primary' is the authorized user's main calendar.",
    )
    time_min: Optional[str] = Field(
        default=None,
        description="RFC3339 lower bound (e.g. '2026-06-01T00:00:00Z').",
    )
    time_max: Optional[str] = Field(
        default=None,
        description="RFC3339 upper bound.",
    )
    query: Optional[str] = Field(
        default=None,
        description="Free-text search across event fields.",
    )
    max_results: int = Field(default=25, description="1 - 250.")


class GetEventArgs(BaseModel):
    calendar_id: str = Field(default="primary")
    event_id: str = Field(description="The calendar event id.")


class GoogleCalendar(agentkit.Integration):
    """Read-only Google Calendar tools."""

    namespace = "gcal"

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_path: Optional[str | Path] = None,
        oauth: Optional[GoogleOAuthClient] = None,
    ) -> None:
        if oauth is not None:
            self._oauth = oauth
            return
        cid = client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        csec = client_secret or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        path = token_path or Path.home() / ".agentkit" / "gcal.json"
        self._oauth = GoogleOAuthClient(
            client_id=cid,
            client_secret=csec,
            scopes=list(CALENDAR_SCOPES),
            token_path=path,
        )

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        headers = await self._oauth.authorized_headers()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{CALENDAR_API}{path}", headers=headers, params=params
            )
            resp.raise_for_status()
            return resp.json()

    @agentkit.tool(
        description="List calendar events. Use time_min/time_max to narrow the window.",
        parameters=ListEventsArgs,
        risk="read",
    )
    async def list_events(self, ctx: agentkit.ToolContext, args: dict) -> dict:
        params: dict[str, Any] = {
            "maxResults": min(int(args.get("max_results", 25)), 250),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        if args.get("time_min"):
            params["timeMin"] = args["time_min"]
        if args.get("time_max"):
            params["timeMax"] = args["time_max"]
        if args.get("query"):
            params["q"] = args["query"]
        cal_id = args.get("calendar_id", "primary")
        data = await self._get(f"/calendars/{cal_id}/events", params=params)
        return {
            "events": [
                {
                    "id": e.get("id"),
                    "summary": e.get("summary"),
                    "start": (e.get("start") or {}).get("dateTime")
                    or (e.get("start") or {}).get("date"),
                    "end": (e.get("end") or {}).get("dateTime")
                    or (e.get("end") or {}).get("date"),
                    "html_link": e.get("htmlLink"),
                    "status": e.get("status"),
                }
                for e in (data.get("items") or [])
            ]
        }

    @agentkit.tool(
        description="Fetch a single calendar event by id.",
        parameters=GetEventArgs,
        risk="read",
    )
    async def get_event(self, ctx: agentkit.ToolContext, args: dict) -> dict:
        cal_id = args.get("calendar_id", "primary")
        data = await self._get(f"/calendars/{cal_id}/events/{args['event_id']}")
        return {
            "id": data.get("id"),
            "summary": data.get("summary"),
            "description": data.get("description"),
            "location": data.get("location"),
            "start": data.get("start"),
            "end": data.get("end"),
            "attendees": [
                {"email": a.get("email"), "response_status": a.get("responseStatus")}
                for a in (data.get("attendees") or [])
            ],
            "status": data.get("status"),
            "html_link": data.get("htmlLink"),
        }
