"""Spotify API client for low-level API operations."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


class SpotifyClient:
    """Low-level client for Spotify Web API operations."""

    _API_BASE_URL = "https://api.spotify.com/v1"
    _ACCOUNTS_BASE_URL = "https://accounts.spotify.com"

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._timeout = httpx.Timeout(connect=0.8, read=2.5, write=2.5, pool=0.8)
        self._limits = httpx.Limits(
            max_connections=80,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=self._limits,
                follow_redirects=False,
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    @staticmethod
    def _assert_status(
        response: httpx.Response,
        *,
        action: str,
        allowed: tuple[int, ...],
    ) -> None:
        if response.status_code in allowed:
            return
        raise Exception(
            f"{action} failed (status={response.status_code}): {response.text}"
        )

    async def refresh_token(self, integration: Integration, db: Session) -> str:
        """Refresh Spotify access token."""
        try:
            if not integration.refresh_token:
                raise Exception("No refresh token available")

            client_id = settings.SPOTIFY_CLIENT_ID
            client_secret = settings.SPOTIFY_CLIENT_SECRET
            if not client_id or not client_secret:
                logger.error("Spotify credentials missing in settings")
                raise Exception("Missing Spotify credentials")

            logger.info(
                "Refreshing Spotify token",
                extra={"user_id": str(integration.user_id)},
            )

            response = await self._get_http_client().post(
                f"{self._ACCOUNTS_BASE_URL}/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": integration.refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            self._assert_status(
                response,
                action="Token refresh",
                allowed=(200,),
            )

            token_data = response.json()

            integration.access_token = token_data["access_token"]
            integration.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )
            integration.updated_at = datetime.now(timezone.utc)

            if "refresh_token" in token_data:
                integration.refresh_token = token_data["refresh_token"]

            db.commit()

            logger.info(
                "Successfully refreshed Spotify token",
                extra={"user_id": str(integration.user_id)},
            )
            return str(integration.access_token)

        except Exception as error:
            logger.error("Failed to refresh Spotify token: %s", error, exc_info=True)
            raise

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
        """Get valid access token, refreshing if needed."""
        if integration.expires_at:
            expires_at = integration.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at < datetime.now(timezone.utc) + timedelta(minutes=5):
                logger.info("Token expired or expiring soon, refreshing")
                return await self.refresh_token(integration, db)

        return str(integration.access_token)

    async def get_current_playback(self, access_token: str) -> dict[str, Any]:
        """Get user's current playback state."""
        response = await self._get_http_client().get(
            f"{self._API_BASE_URL}/me/player",
            headers=self._auth_headers(access_token),
        )

        if response.status_code == 204:
            return {"is_playing": False, "device": None}

        self._assert_status(
            response,
            action="Get current playback",
            allowed=(200,),
        )
        return response.json()

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

        response = await self._get_http_client().put(
            url,
            json=body if body else None,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Play", allowed=(200, 204))

    async def pause(self, access_token: str, device_id: Optional[str] = None) -> None:
        """Pause playback."""
        url = f"{self._API_BASE_URL}/me/player/pause"
        if device_id:
            url += f"?device_id={device_id}"

        response = await self._get_http_client().put(
            url,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Pause", allowed=(200, 204))

    async def skip_next(
        self, access_token: str, device_id: Optional[str] = None
    ) -> None:
        """Skip to next track."""
        url = f"{self._API_BASE_URL}/me/player/next"
        if device_id:
            url += f"?device_id={device_id}"

        response = await self._get_http_client().post(
            url,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Skip next", allowed=(200, 204))

    async def skip_previous(
        self, access_token: str, device_id: Optional[str] = None
    ) -> None:
        """Skip to previous track."""
        url = f"{self._API_BASE_URL}/me/player/previous"
        if device_id:
            url += f"?device_id={device_id}"

        response = await self._get_http_client().post(
            url,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Skip previous", allowed=(200, 204))

    async def search(
        self,
        access_token: str,
        query: str,
        types: str = "track,artist,album",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for tracks, artists, albums, or playlists."""
        response = await self._get_http_client().get(
            f"{self._API_BASE_URL}/search",
            params={"q": query, "type": types, "limit": limit},
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Search", allowed=(200,))
        return response.json()

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

        response = await self._get_http_client().put(
            url,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Set volume", allowed=(200, 204))

    async def get_user_playlists(
        self, access_token: str, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Get user's playlists."""
        response = await self._get_http_client().get(
            f"{self._API_BASE_URL}/me/playlists",
            params={"limit": limit, "offset": offset},
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Get user playlists", allowed=(200,))
        return response.json()

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

        while next_url and len(items) < max_items:
            params = {
                "limit": page_limit,
                "fields": "items(track(id,name,uri,popularity,artists(name),album(name,images))),next",
            }
            response = await self._get_http_client().get(
                next_url,
                params=params,
                headers=self._auth_headers(access_token),
            )
            self._assert_status(
                response,
                action="Get playlist tracks",
                allowed=(200,),
            )

            payload = response.json()
            page_items = payload.get("items", [])
            if isinstance(page_items, list):
                for row in page_items:
                    if isinstance(row, dict):
                        items.append(row)
                        if len(items) >= max_items:
                            break
            next_value = payload.get("next")
            next_url = str(next_value) if isinstance(next_value, str) else None

        return items[:max_items]

    async def get_available_devices(self, access_token: str) -> dict[str, Any]:
        """Get user's available devices."""
        response = await self._get_http_client().get(
            f"{self._API_BASE_URL}/me/player/devices",
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Get devices", allowed=(200,))
        return response.json()

    async def transfer_playback(
        self, access_token: str, device_id: str, play: bool = False
    ) -> None:
        """Transfer playback to a different device."""
        response = await self._get_http_client().put(
            f"{self._API_BASE_URL}/me/player",
            json={"device_ids": [device_id], "play": play},
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Transfer playback", allowed=(200, 204))

    async def add_to_queue(
        self, access_token: str, uri: str, device_id: Optional[str] = None
    ) -> None:
        """Add a track to the current playback queue."""
        params: dict[str, str] = {"uri": uri}
        if device_id:
            params["device_id"] = device_id

        response = await self._get_http_client().post(
            f"{self._API_BASE_URL}/me/player/queue",
            params=params,
            headers=self._auth_headers(access_token),
        )
        self._assert_status(response, action="Add to queue", allowed=(200, 204))


spotify_client = SpotifyClient()
