"""Gmail integration -- read-only access via OAuth 2.0.

Installed by `agentkit add gmail`. See SETUP.md (next to this file) for
the Google Cloud OAuth client step.

Auth: set ``GOOGLE_OAUTH_CLIENT_ID`` and ``GOOGLE_OAUTH_CLIENT_SECRET``
in your environment. The first call to a Gmail tool runs Google's
consent flow in your browser; tokens persist to ``~/.agentkit/gmail.json``
by default.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field

import agentkit
from agentkit.integrations.oauth import GoogleOAuthClient


GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)


class ListMessagesArgs(BaseModel):
    query: str = Field(
        default="",
        description="Gmail search query (e.g. 'from:foo subject:bar is:unread').",
    )
    max_results: int = Field(default=10, description="1 - 100.")


class GetMessageArgs(BaseModel):
    message_id: str = Field(description="The Gmail message id.")


class Gmail(agentkit.Integration):
    """Read-only Gmail tools."""

    namespace = "gmail"

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
        path = token_path or Path.home() / ".agentkit" / "gmail.json"
        self._oauth = GoogleOAuthClient(
            client_id=cid,
            client_secret=csec,
            scopes=list(GMAIL_SCOPES),
            token_path=path,
        )

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        headers = await self._oauth.authorized_headers()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{GMAIL_API}{path}", headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    @agentkit.tool(
        description="List Gmail messages matching a search query.",
        parameters=ListMessagesArgs,
        risk="read",
    )
    async def list_messages(self, ctx: agentkit.ToolContext, args: dict) -> dict:
        params: dict[str, Any] = {
            "maxResults": min(int(args.get("max_results", 10)), 100),
        }
        if args.get("query"):
            params["q"] = args["query"]
        data = await self._get("/users/me/messages", params=params)
        return {
            "result_size_estimate": data.get("resultSizeEstimate", 0),
            "messages": [
                {"id": m.get("id"), "thread_id": m.get("threadId")}
                for m in (data.get("messages") or [])
            ],
        }

    @agentkit.tool(
        description="Fetch a single Gmail message by id (headers + snippet).",
        parameters=GetMessageArgs,
        risk="read",
    )
    async def get_message(self, ctx: agentkit.ToolContext, args: dict) -> dict:
        data = await self._get(
            f"/users/me/messages/{args['message_id']}",
            params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},
        )
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "label_ids": data.get("labelIds", []),
            "snippet": data.get("snippet"),
            "from": headers.get("From"),
            "to": headers.get("To"),
            "subject": headers.get("Subject"),
            "date": headers.get("Date"),
        }


def _decode_body(part: dict) -> Optional[str]:
    """Helper: decode a base64url body part to text. Unused by the headline
    tools above, but exported here for users who want to extend the
    integration to fetch full message bodies."""
    body = part.get("body") or {}
    data = body.get("data")
    if not data:
        return None
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    except Exception:
        return None
