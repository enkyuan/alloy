"""Spotify API client for low-level API operations."""

import logging
from datetime import datetime, timedelta, timezone
from app.services.integrations.base import ExpiringOAuthIntegrationService
from typing import Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.integration import Integration
from app.services.integrations.errors import (
    IntegrationAuthError,
    classify_http_error,
)
from app.services.lifecycle import register_close_handler

logger = logging.getLogger(__name__)


class SpotifyClient(ExpiringOAuthIntegrationService):
    """Low-level client for Spotify Web API operations."""

    SERVICE_NAME = "spotify"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    _API_BASE_URL = "https://api.spotify.com/v1"

    def _oauth_client_credentials(self) -> tuple[Optional[str], Optional[str]]:
        return settings.SPOTIFY_CLIENT_ID, settings.SPOTIFY_CLIENT_SECRET

    async def get_current_playback(self, access_token: str) -> dict[str, Any]:
        """Get user's current playback state."""
        return await self._request_json(
            "GET",
            f"{self._API_BASE_URL}/me/player",
            action="Get current playback",
            headers=self._auth_headers(access_token),
            default={"is_playing": False, "device": None},
            expected_status=(200, 204),
        )

    async def play(
        self,
        access_token: str,
        uri: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> None:
        """Start or resume playback."""
        url = f"{self._API_BASE_URL}/me/player/play"
        if device_id:
            url += f"?device_id={device_id}"

        body: dict[str, object] = {}
        if uri:
            if uri.startswith("spotify:track:"):
                body["uris"] = [uri]
            else:
                body["context_uri"] = uri

        await self._request_no_content(
            "PUT",
            url,
            action="Play",
            headers=self._auth_headers(access_token),
            json=body if body else None,
            expected_status=(200, 204),
        )

    async def pause(self, access_token: str, device_id: Optional[str] = None) -> None:
        """Pause playback."""
        url = f"{self._API_BASE_URL}/me/player/pause"
        if device_id:
            url += f"?device_id={device_id}"

        await self._request_no_content(
            "PUT",
            url,
            action="Pause",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def skip_next(
        self, access_token: str, device_id: Optional[str] = None
    ) -> None:
        """Skip to next track."""
        url = f"{self._API_BASE_URL}/me/player/next"
        if device_id:
            url += f"?device_id={device_id}"

        await self._request_no_content(
            "POST",
            url,
            action="Skip next",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def skip_previous(
        self, access_token: str, device_id: Optional[str] = None
    ) -> None:
        """Skip to previous track."""
        url = f"{self._API_BASE_URL}/me/player/previous"
        if device_id:
            url += f"?device_id={device_id}"

        await self._request_no_content(
            "POST",
            url,
            action="Skip previous",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def search(
        self,
        access_token: str,
        query: str,
        types: str = "track,artist,album",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for tracks, artists, albums, or playlists."""
        return await self._request_json(
            "GET",
            f"{self._API_BASE_URL}/search",
            action="Search",
            headers=self._auth_headers(access_token),
            params={"q": query, "type": types, "limit": limit},
        )

    async def set_volume(
        self,
        access_token: str,
        volume_percent: int,
        device_id: Optional[str] = None,
    ) -> None:
        """Set playback volume."""
        url = f"{self._API_BASE_URL}/me/player/volume?volume_percent={volume_percent}"
        if device_id:
            url += f"&device_id={device_id}"

        await self._request_no_content(
            "PUT",
            url,
            action="Set volume",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def get_user_playlists(
        self, access_token: str, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Get user's playlists."""
        return await self._request_json(
            "GET",
            f"{self._API_BASE_URL}/me/playlists",
            action="Get user playlists",
            headers=self._auth_headers(access_token),
            params={"limit": limit, "offset": offset},
        )

    async def get_playlist_tracks(
        self,
        access_token: str,
        playlist_id: str,
        max_items: int = 200,
    ) -> list[dict[str, Any]]:
        """Get tracks for a playlist."""
        if max_items <= 0:
            return []

        items: list[dict[str, Any]] = []
        next_url: Optional[str] = (
            f"{self._API_BASE_URL}/playlists/{playlist_id}/tracks"
        )
        page_limit = min(100, max_items)

        is_first_page = True
        while next_url and len(items) < max_items:
            params = {
                "limit": page_limit,
                "fields": "items(track(id,name,uri,popularity,artists(name),album(name,images))),next",
            }
            # Custom handling for pagination loop since we need to extract next_url
            response = await self._request_json(
                "GET",
                next_url,
                action="Get playlist tracks",
                headers=self._auth_headers(access_token),
                params=params if is_first_page else None,
            )
            is_first_page = False
            # Wait, _request uses self._get_http_client().request(..., url=url)
            # If url is absolute, httpx uses it.
            
            # The issue: In the loop, I need `response`. `_request_json` returns the dict.
            payload = response
            # Start of loop logic adaptation
            
            page_items = payload.get("items", [])
            if isinstance(page_items, list):
                for row in page_items:
                    if isinstance(row, dict):
                        items.append(row)
                        if len(items) >= max_items:
                            break
            next_value = payload.get("next")
            next_url = str(next_value) if isinstance(next_value, str) else None
            
            # Reset params for next iteration if next_url is provided (pagination URLs usually have everything)
            # If next_url comes from Spotify, it has params. We shouldn't pass `params` again.
            # So I should only use params for the INITIAL URL constructed manually.
            # Refactoring this loop slightly to handle that.
            
        return items[:max_items]

    async def get_available_devices(self, access_token: str) -> dict[str, Any]:
        """Get user's available devices."""
        return await self._request_json(
            "GET",
            f"{self._API_BASE_URL}/me/player/devices",
            action="Get devices",
            headers=self._auth_headers(access_token),
        )

    async def transfer_playback(
        self, access_token: str, device_id: str, play: bool = False
    ) -> None:
        """Transfer playback to a different device."""
        await self._request_no_content(
            "PUT",
            f"{self._API_BASE_URL}/me/player",
            action="Transfer playback",
            headers=self._auth_headers(access_token),
            json={"device_ids": [device_id], "play": play},
            expected_status=(200, 204),
        )

    async def add_to_queue(
        self, access_token: str, uri: str, device_id: Optional[str] = None
    ) -> None:
        """Add a track to the current playback queue."""
        params: dict[str, str] = {"uri": uri}
        if device_id:
            params["device_id"] = device_id

        await self._request_no_content(
            "POST",
            f"{self._API_BASE_URL}/me/player/queue",
            action="Add to queue",
            headers=self._auth_headers(access_token),
            params=params,
            expected_status=(200, 204),
        )


spotify_client = SpotifyClient()
