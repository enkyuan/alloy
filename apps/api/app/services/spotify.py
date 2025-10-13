"""Spotify API service."""
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


class SpotifyService:
    """Service for Spotify API operations."""

    async def refresh_token(self, integration: Integration, db: Session) -> str:
        """Refresh Spotify access token.

        Args:
            integration: Integration model with refresh token
            db: Database session

        Returns:
            New access token

        Raises:
            Exception: If token refresh fails
        """
        try:
            if not integration.refresh_token:
                raise Exception("No refresh token available")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": integration.refresh_token,
                        "client_id": settings.SPOTIFY_CLIENT_ID,
                        "client_secret": settings.SPOTIFY_CLIENT_SECRET
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )

                if response.status_code != 200:
                    logger.error(f"Token refresh failed: {response.text}")
                    raise Exception(f"Failed to refresh token: {response.text}")

                token_data = response.json()

                # Update integration
                integration.access_token = token_data["access_token"]
                integration.expires_at = datetime.utcnow() + timedelta(
                    seconds=token_data.get("expires_in", 3600)
                )
                integration.updated_at = datetime.utcnow()

                # Spotify doesn't always return new refresh token
                if "refresh_token" in token_data:
                    integration.refresh_token = token_data["refresh_token"]

                db.commit()

                logger.info(f"Successfully refreshed Spotify token for user {integration.user_id}")
                return integration.access_token

        except Exception as e:
            logger.error(f"Failed to refresh Spotify token: {str(e)}", exc_info=True)
            raise

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
        """Get valid access token, refreshing if needed.

        Args:
            integration: Integration model
            db: Database session

        Returns:
            Valid access token

        Raises:
            Exception: If token refresh fails
        """
        # Check if token is expired or expires soon (within 5 minutes)
        if integration.expires_at and \
           integration.expires_at < datetime.utcnow() + timedelta(minutes=5):
            logger.info("Token expired or expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return integration.access_token

    async def get_current_playback(self, access_token: str) -> dict:
        """Get user's current playback state.

        Args:
            access_token: Valid Spotify access token

        Returns:
            Current playback data

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/player",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code == 204:
                return {"is_playing": False, "device": None}

            if response.status_code != 200:
                raise Exception(f"Failed to get playback: {response.text}")

            return response.json()

    async def play(
        self,
        access_token: str,
        uri: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> None:
        """Start or resume playback.

        Args:
            access_token: Valid Spotify access token
            uri: Optional Spotify URI to play
            device_id: Optional device ID to play on

        Raises:
            Exception: If API call fails
        """
        url = "https://api.spotify.com/v1/me/player/play"
        if device_id:
            url += f"?device_id={device_id}"

        body = {}
        if uri:
            if uri.startswith("spotify:track:"):
                body["uris"] = [uri]
            else:
                body["context_uri"] = uri

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                json=body if body else None,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to play: {response.text}")

    async def pause(self, access_token: str, device_id: Optional[str] = None) -> None:
        """Pause playback.

        Args:
            access_token: Valid Spotify access token
            device_id: Optional device ID to pause on

        Raises:
            Exception: If API call fails
        """
        url = "https://api.spotify.com/v1/me/player/pause"
        if device_id:
            url += f"?device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to pause: {response.text}")

    async def skip_next(self, access_token: str, device_id: Optional[str] = None) -> None:
        """Skip to next track.

        Args:
            access_token: Valid Spotify access token
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = "https://api.spotify.com/v1/me/player/next"
        if device_id:
            url += f"?device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to skip: {response.text}")

    async def skip_previous(self, access_token: str, device_id: Optional[str] = None) -> None:
        """Skip to previous track.

        Args:
            access_token: Valid Spotify access token
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = "https://api.spotify.com/v1/me/player/previous"
        if device_id:
            url += f"?device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to skip back: {response.text}")

    async def search(
        self,
        access_token: str,
        query: str,
        types: str = "track,artist,album",
        limit: int = 10
    ) -> dict:
        """Search for tracks, artists, albums, or playlists.

        Args:
            access_token: Valid Spotify access token
            query: Search query
            types: Comma-separated list of types (track, artist, album, playlist)
            limit: Number of results per type

        Returns:
            Search results

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/search",
                params={"q": query, "type": types, "limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Search failed: {response.text}")

            return response.json()

    async def set_volume(
        self,
        access_token: str,
        volume_percent: int,
        device_id: Optional[str] = None
    ) -> None:
        """Set playback volume.

        Args:
            access_token: Valid Spotify access token
            volume_percent: Volume level (0-100)
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = f"https://api.spotify.com/v1/me/player/volume?volume_percent={volume_percent}"
        if device_id:
            url += f"&device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to set volume: {response.text}")


spotify_service = SpotifyService()
