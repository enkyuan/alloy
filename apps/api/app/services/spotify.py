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

    # ============================================================================
    # Tracks
    # ============================================================================

    async def get_track(self, access_token: str, track_id: str) -> dict:
        """Get Spotify track details.

        Args:
            access_token: Valid Spotify access token
            track_id: Spotify track ID

        Returns:
            Track details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/tracks/{track_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get track: {response.text}")

            return response.json()

    async def get_audio_features(self, access_token: str, track_id: str) -> dict:
        """Get audio features for a track.

        Args:
            access_token: Valid Spotify access token
            track_id: Spotify track ID

        Returns:
            Audio features (tempo, energy, danceability, etc.)

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/audio-features/{track_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get audio features: {response.text}")

            return response.json()

    # ============================================================================
    # Playlists
    # ============================================================================

    async def get_user_playlists(self, access_token: str, limit: int = 20) -> dict:
        """Get user's playlists.

        Args:
            access_token: Valid Spotify access token
            limit: Number of playlists to return

        Returns:
            User's playlists

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/playlists",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get playlists: {response.text}")

            return response.json()

    async def get_playlist(self, access_token: str, playlist_id: str) -> dict:
        """Get playlist details.

        Args:
            access_token: Valid Spotify access token
            playlist_id: Spotify playlist ID

        Returns:
            Playlist details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get playlist: {response.text}")

            return response.json()

    async def add_to_playlist(
        self,
        access_token: str,
        playlist_id: str,
        track_uris: list[str]
    ) -> dict:
        """Add tracks to a playlist.

        Args:
            access_token: Valid Spotify access token
            playlist_id: Spotify playlist ID
            track_uris: List of track URIs to add

        Returns:
            Snapshot ID

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                json={"uris": track_uris},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to add to playlist: {response.text}")

            return response.json()

    # ============================================================================
    # Albums
    # ============================================================================

    async def get_album(self, access_token: str, album_id: str) -> dict:
        """Get album details.

        Args:
            access_token: Valid Spotify access token
            album_id: Spotify album ID

        Returns:
            Album details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/albums/{album_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get album: {response.text}")

            return response.json()

    # ============================================================================
    # Artists
    # ============================================================================

    async def get_artist(self, access_token: str, artist_id: str) -> dict:
        """Get artist details.

        Args:
            access_token: Valid Spotify access token
            artist_id: Spotify artist ID

        Returns:
            Artist details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/artists/{artist_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get artist: {response.text}")

            return response.json()

    async def get_artist_top_tracks(
        self,
        access_token: str,
        artist_id: str,
        market: str = "US"
    ) -> dict:
        """Get artist's top tracks.

        Args:
            access_token: Valid Spotify access token
            artist_id: Spotify artist ID
            market: Market code (e.g., "US")

        Returns:
            Artist's top tracks

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
                params={"market": market},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get artist top tracks: {response.text}")

            return response.json()

    async def get_related_artists(self, access_token: str, artist_id: str) -> dict:
        """Get related artists.

        Args:
            access_token: Valid Spotify access token
            artist_id: Spotify artist ID

        Returns:
            Related artists

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/artists/{artist_id}/related-artists",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get related artists: {response.text}")

            return response.json()

    # ============================================================================
    # Library
    # ============================================================================

    async def get_saved_tracks(self, access_token: str, limit: int = 20) -> dict:
        """Get user's saved tracks.

        Args:
            access_token: Valid Spotify access token
            limit: Number of tracks to return

        Returns:
            Saved tracks

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/tracks",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get saved tracks: {response.text}")

            return response.json()

    async def save_tracks(self, access_token: str, track_ids: list[str]) -> None:
        """Save tracks to library.

        Args:
            access_token: Valid Spotify access token
            track_ids: List of track IDs to save

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.put(
                "https://api.spotify.com/v1/me/tracks",
                json={"ids": track_ids},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to save tracks: {response.text}")

    async def remove_saved_tracks(self, access_token: str, track_ids: list[str]) -> None:
        """Remove saved tracks from library.

        Args:
            access_token: Valid Spotify access token
            track_ids: List of track IDs to remove

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                "https://api.spotify.com/v1/me/tracks",
                json={"ids": track_ids},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to remove tracks: {response.text}")

    # ============================================================================
    # User Profile & Personalization
    # ============================================================================

    async def get_current_user_profile(self, access_token: str) -> dict:
        """Get current user's profile.

        Args:
            access_token: Valid Spotify access token

        Returns:
            User profile data

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get user profile: {response.text}")

            return response.json()

    async def get_top_items(
        self,
        access_token: str,
        item_type: str = "tracks",
        time_range: str = "medium_term",
        limit: int = 20
    ) -> dict:
        """Get user's top tracks or artists.

        Args:
            access_token: Valid Spotify access token
            item_type: "tracks" or "artists"
            time_range: "short_term", "medium_term", or "long_term"
            limit: Number of items to return

        Returns:
            Top items

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.spotify.com/v1/me/top/{item_type}",
                params={"time_range": time_range, "limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get top {item_type}: {response.text}")

            return response.json()

    async def get_recently_played(self, access_token: str, limit: int = 20) -> dict:
        """Get recently played tracks.

        Args:
            access_token: Valid Spotify access token
            limit: Number of tracks to return

        Returns:
            Recently played tracks

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/player/recently-played",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get recently played: {response.text}")

            return response.json()

    # ============================================================================
    # Recommendations
    # ============================================================================

    async def get_recommendations(
        self,
        access_token: str,
        seed_tracks: Optional[list[str]] = None,
        seed_artists: Optional[list[str]] = None,
        seed_genres: Optional[list[str]] = None,
        limit: int = 20
    ) -> dict:
        """Get recommendations based on seeds.

        Args:
            access_token: Valid Spotify access token
            seed_tracks: List of track IDs (max 5 combined seeds)
            seed_artists: List of artist IDs
            seed_genres: List of genre names
            limit: Number of recommendations

        Returns:
            Recommended tracks

        Raises:
            Exception: If API call fails
        """
        params = {"limit": limit}
        if seed_tracks:
            params["seed_tracks"] = ",".join(seed_tracks)
        if seed_artists:
            params["seed_artists"] = ",".join(seed_artists)
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/recommendations",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get recommendations: {response.text}")

            return response.json()

    async def get_available_genre_seeds(self, access_token: str) -> dict:
        """Get available genre seeds for recommendations.

        Args:
            access_token: Valid Spotify access token

        Returns:
            Available genres

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/recommendations/available-genre-seeds",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get genre seeds: {response.text}")

            return response.json()

    # ============================================================================
    # Player - Advanced Controls
    # ============================================================================

    async def get_available_devices(self, access_token: str) -> dict:
        """Get user's available devices.

        Args:
            access_token: Valid Spotify access token

        Returns:
            Available devices

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.spotify.com/v1/me/player/devices",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get devices: {response.text}")

            return response.json()

    async def transfer_playback(
        self,
        access_token: str,
        device_id: str,
        play: bool = False
    ) -> None:
        """Transfer playback to a different device.

        Args:
            access_token: Valid Spotify access token
            device_id: Target device ID
            play: Whether to start playing on new device

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.put(
                "https://api.spotify.com/v1/me/player",
                json={"device_ids": [device_id], "play": play},
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to transfer playback: {response.text}")

    async def set_shuffle(
        self,
        access_token: str,
        state: bool,
        device_id: Optional[str] = None
    ) -> None:
        """Toggle shuffle mode.

        Args:
            access_token: Valid Spotify access token
            state: True to enable shuffle, False to disable
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = f"https://api.spotify.com/v1/me/player/shuffle?state={str(state).lower()}"
        if device_id:
            url += f"&device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to set shuffle: {response.text}")

    async def set_repeat(
        self,
        access_token: str,
        state: str,
        device_id: Optional[str] = None
    ) -> None:
        """Set repeat mode.

        Args:
            access_token: Valid Spotify access token
            state: "track", "context", or "off"
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = f"https://api.spotify.com/v1/me/player/repeat?state={state}"
        if device_id:
            url += f"&device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to set repeat: {response.text}")

    async def add_to_queue(
        self,
        access_token: str,
        uri: str,
        device_id: Optional[str] = None
    ) -> None:
        """Add item to queue.

        Args:
            access_token: Valid Spotify access token
            uri: Spotify URI to add
            device_id: Optional device ID

        Raises:
            Exception: If API call fails
        """
        url = f"https://api.spotify.com/v1/me/player/queue?uri={uri}"
        if device_id:
            url += f"&device_id={device_id}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to add to queue: {response.text}")


spotify_service = SpotifyService()
