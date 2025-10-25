"""Spotify Controller for voice command execution."""
import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class SpotifyControllerError(Exception):
    """Base exception for SpotifyController errors."""
    pass


class NoActiveDeviceError(SpotifyControllerError):
    """Raised when no active Spotify device is found."""
    def __init__(self, message: str = "No active Spotify device found. Please open Spotify on a device."):
        self.message = message
        super().__init__(self.message)


class SearchNoResultsError(SpotifyControllerError):
    """Raised when search returns no results."""
    def __init__(self, query: str, search_type: str = "track"):
        self.query = query
        self.search_type = search_type
        self.message = f"No {search_type} found for '{query}'"
        super().__init__(self.message)


class SpotifyAPIError(SpotifyControllerError):
    """Raised when Spotify API call fails."""
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.message = message
        self.original_error = original_error
        super().__init__(self.message)


class PremiumRequiredError(SpotifyControllerError):
    """Raised when operation requires Spotify Premium."""
    def __init__(self, message: str = "This feature requires Spotify Premium"):
        self.message = message
        super().__init__(self.message)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    message: str
    data: dict
    error: Optional[str] = None


# ============================================================================
# Spotify Controller
# ============================================================================


class SpotifyController:
    """Controller for executing Spotify commands from voice agent."""

    def __init__(self, spotify_service: "SpotifyService"):
        """Initialize SpotifyController.

        Args:
            spotify_service: SpotifyService instance for API calls
        """
        self.spotify = spotify_service

    async def get_active_device(self, access_token: str) -> Optional[str]:
        """Get active device ID with fallback handling.

        Args:
            access_token: Valid Spotify access token

        Returns:
            Active device ID or None if no device found

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            # First check current playback for active device
            playback = await self.spotify.get_current_playback(access_token)
            if playback.get("device") and playback["device"].get("id"):
                logger.info(f"Found active device from playback: {playback['device']['name']}")
                return playback["device"]["id"]

            # Fallback: get available devices and use first one
            devices_response = await self.spotify.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            if not devices:
                logger.warning("No devices available")
                return None

            # Prefer active device
            for device in devices:
                if device.get("is_active"):
                    logger.info(f"Found active device: {device['name']}")
                    return device["id"]

            # Use first available device
            first_device = devices[0]
            logger.info(f"Using first available device: {first_device['name']}")
            return first_device["id"]

        except Exception as e:
            logger.error(f"Failed to get active device: {str(e)}")
            raise SpotifyAPIError("Failed to get device information", e)

    async def search_and_play_track(
        self,
        query: str,
        access_token: str,
        artist: Optional[str] = None
    ) -> CommandResult:
        """Search for a track and play it (most popular result).

        Args:
            query: Track name to search for
            access_token: Valid Spotify access token
            artist: Optional artist name to refine search

        Returns:
            CommandResult with track information

        Raises:
            NoActiveDeviceError: If no device available
            SearchNoResultsError: If no tracks found
            SpotifyAPIError: If API call fails
        """
        try:
            # Build search query
            search_query = query
            if artist:
                search_query = f"track:{query} artist:{artist}"

            logger.info(f"Searching for track: {search_query}")

            # Search for track
            search_results = await self.spotify.search(
                access_token=access_token,
                query=search_query,
                types="track",
                limit=10
            )

            tracks = search_results.get("tracks", {}).get("items", [])
            if not tracks:
                raise SearchNoResultsError(query, "track")

            # Select most popular track (highest popularity score)
            selected_track = max(tracks, key=lambda t: t.get("popularity", 0))

            track_name = selected_track["name"]
            track_artist = selected_track["artists"][0]["name"]
            track_uri = selected_track["uri"]
            track_id = selected_track["id"]

            logger.info(f"Selected track: {track_name} by {track_artist}")

            # Get active device
            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            # Play the track
            await self.spotify.play(
                access_token=access_token,
                uri=track_uri,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message=f"Now playing '{track_name}' by {track_artist}",
                data={
                    "track_name": track_name,
                    "artist": track_artist,
                    "album": selected_track.get("album", {}).get("name", ""),
                    "uri": track_uri,
                    "track_id": track_id,
                    "album_art": selected_track.get("album", {}).get("images", [{}])[0].get("url") if selected_track.get("album", {}).get("images") else None
                }
            )

        except (NoActiveDeviceError, SearchNoResultsError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play track: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to play track: {str(e)}", e)

    async def search_and_play_playlist(
        self,
        query: str,
        access_token: str,
        user_playlists_only: bool = False
    ) -> CommandResult:
        """Search for a playlist and play it.

        Args:
            query: Playlist name to search for
            access_token: Valid Spotify access token
            user_playlists_only: If True, only search user's own playlists

        Returns:
            CommandResult with playlist information

        Raises:
            NoActiveDeviceError: If no device available
            SearchNoResultsError: If no playlists found
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info(f"Searching for playlist: {query} (user_only={user_playlists_only})")

            playlists = []

            if user_playlists_only:
                # Search user's playlists
                user_playlists_response = await self.spotify.get_user_playlists(
                    access_token=access_token,
                    limit=50
                )
                all_playlists = user_playlists_response.get("items", [])

                # Filter by query (case-insensitive)
                query_lower = query.lower()
                playlists = [
                    p for p in all_playlists
                    if query_lower in p["name"].lower()
                ]
            else:
                # Search all playlists
                search_results = await self.spotify.search(
                    access_token=access_token,
                    query=query,
                    types="playlist",
                    limit=10
                )
                playlists = search_results.get("playlists", {}).get("items", [])

            if not playlists:
                raise SearchNoResultsError(query, "playlist")

            # Select first matching playlist
            selected_playlist = playlists[0]
            playlist_name = selected_playlist["name"]
            playlist_uri = selected_playlist["uri"]
            playlist_id = selected_playlist["id"]

            logger.info(f"Selected playlist: {playlist_name}")

            # Get active device
            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            # Play the playlist
            await self.spotify.play(
                access_token=access_token,
                uri=playlist_uri,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message=f"Now playing playlist '{playlist_name}'",
                data={
                    "playlist_name": playlist_name,
                    "uri": playlist_uri,
                    "playlist_id": playlist_id,
                    "owner": selected_playlist.get("owner", {}).get("display_name", ""),
                    "tracks_total": selected_playlist.get("tracks", {}).get("total", 0)
                }
            )

        except (NoActiveDeviceError, SearchNoResultsError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play playlist: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to play playlist: {str(e)}", e)

    async def search_and_play_album(
        self,
        query: str,
        access_token: str,
        artist: Optional[str] = None
    ) -> CommandResult:
        """Search for an album and play it.

        Args:
            query: Album name to search for
            access_token: Valid Spotify access token
            artist: Optional artist name to refine search

        Returns:
            CommandResult with album information

        Raises:
            NoActiveDeviceError: If no device available
            SearchNoResultsError: If no albums found
            SpotifyAPIError: If API call fails
        """
        try:
            # Build search query
            search_query = query
            if artist:
                search_query = f"album:{query} artist:{artist}"

            logger.info(f"Searching for album: {search_query}")

            # Search for album
            search_results = await self.spotify.search(
                access_token=access_token,
                query=search_query,
                types="album",
                limit=10
            )

            albums = search_results.get("albums", {}).get("items", [])
            if not albums:
                raise SearchNoResultsError(query, "album")

            # Select first album (most relevant)
            selected_album = albums[0]
            album_name = selected_album["name"]
            album_artist = selected_album["artists"][0]["name"]
            album_uri = selected_album["uri"]
            album_id = selected_album["id"]

            logger.info(f"Selected album: {album_name} by {album_artist}")

            # Get active device
            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            # Play the album
            await self.spotify.play(
                access_token=access_token,
                uri=album_uri,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message=f"Now playing album '{album_name}' by {album_artist}",
                data={
                    "album_name": album_name,
                    "artist": album_artist,
                    "uri": album_uri,
                    "album_id": album_id,
                    "release_date": selected_album.get("release_date", ""),
                    "total_tracks": selected_album.get("total_tracks", 0),
                    "album_art": selected_album.get("images", [{}])[0].get("url") if selected_album.get("images") else None
                }
            )

        except (NoActiveDeviceError, SearchNoResultsError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play album: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to play album: {str(e)}", e)

    async def pause_playback(self, access_token: str) -> CommandResult:
        """Pause current playback.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming pause

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Pausing playback")

            device_id = await self.get_active_device(access_token)

            await self.spotify.pause(
                access_token=access_token,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message="Playback paused",
                data={}
            )

        except Exception as e:
            logger.error(f"Failed to pause playback: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to pause: {str(e)}", e)

    async def resume_playback(self, access_token: str) -> CommandResult:
        """Resume paused playback.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming resume

        Raises:
            NoActiveDeviceError: If no device available
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Resuming playback")

            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            await self.spotify.play(
                access_token=access_token,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message="Playback resumed",
                data={}
            )

        except NoActiveDeviceError:
            raise
        except Exception as e:
            logger.error(f"Failed to resume playback: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to resume: {str(e)}", e)

    async def next_track(self, access_token: str) -> CommandResult:
        """Skip to next track.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming skip

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Skipping to next track")

            device_id = await self.get_active_device(access_token)

            await self.spotify.skip_next(
                access_token=access_token,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message="Skipped to next track",
                data={}
            )

        except Exception as e:
            logger.error(f"Failed to skip track: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to skip: {str(e)}", e)

    async def previous_track(self, access_token: str) -> CommandResult:
        """Skip to previous track.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming skip back

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Skipping to previous track")

            device_id = await self.get_active_device(access_token)

            await self.spotify.skip_previous(
                access_token=access_token,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message="Skipped to previous track",
                data={}
            )

        except Exception as e:
            logger.error(f"Failed to skip back: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to skip back: {str(e)}", e)

    async def set_volume(
        self,
        access_token: str,
        volume_percent: int
    ) -> CommandResult:
        """Set playback volume.

        Args:
            access_token: Valid Spotify access token
            volume_percent: Volume level (0-100)

        Returns:
            CommandResult confirming volume change

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            # Clamp volume to valid range
            volume_percent = max(0, min(100, volume_percent))

            logger.info(f"Setting volume to {volume_percent}%")

            device_id = await self.get_active_device(access_token)

            await self.spotify.set_volume(
                access_token=access_token,
                volume_percent=volume_percent,
                device_id=device_id
            )

            return CommandResult(
                success=True,
                message=f"Volume set to {volume_percent}%",
                data={"volume": volume_percent}
            )

        except Exception as e:
            logger.error(f"Failed to set volume: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to set volume: {str(e)}", e)

    async def get_available_devices(self, access_token: str) -> CommandResult:
        """Get list of available devices.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult with device list

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Getting available devices")

            devices_response = await self.spotify.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            device_list = [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "type": d["type"],
                    "is_active": d.get("is_active", False),
                    "volume_percent": d.get("volume_percent", 0)
                }
                for d in devices
            ]

            if not devices:
                message = "No devices available"
            else:
                device_names = [d["name"] for d in device_list]
                message = f"Available devices: {', '.join(device_names)}"

            return CommandResult(
                success=True,
                message=message,
                data={"devices": device_list}
            )

        except Exception as e:
            logger.error(f"Failed to get devices: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to get devices: {str(e)}", e)

    async def switch_device(
        self,
        access_token: str,
        device_name: Optional[str] = None,
        device_id: Optional[str] = None,
        start_playback: bool = True
    ) -> CommandResult:
        """Switch playback to a different device.

        Args:
            access_token: Valid Spotify access token
            device_name: Name of device to switch to (fuzzy matched)
            device_id: Specific device ID to switch to
            start_playback: Whether to start playing on the new device

        Returns:
            CommandResult confirming device switch

        Raises:
            NoActiveDeviceError: If no matching device found
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info(f"Switching device: name={device_name}, id={device_id}")

            # Get available devices
            devices_response = await self.spotify.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            if not devices:
                raise NoActiveDeviceError("No devices available to switch to")

            # Find target device
            target_device = None

            if device_id:
                # Find by exact ID
                target_device = next((d for d in devices if d["id"] == device_id), None)
            elif device_name:
                # Find by name (case-insensitive, fuzzy match)
                device_name_lower = device_name.lower()
                
                # First try exact match
                target_device = next(
                    (d for d in devices if d["name"].lower() == device_name_lower),
                    None
                )
                
                # If no exact match, try partial match
                if not target_device:
                    target_device = next(
                        (d for d in devices if device_name_lower in d["name"].lower()),
                        None
                    )

            if not target_device:
                available_names = [d["name"] for d in devices]
                raise NoActiveDeviceError(
                    f"Device '{device_name or device_id}' not found. "
                    f"Available devices: {', '.join(available_names)}"
                )

            # Transfer playback to target device
            await self.spotify.transfer_playback(
                access_token=access_token,
                device_id=target_device["id"],
                play=start_playback
            )

            logger.info(f"Successfully switched to device: {target_device['name']}")

            return CommandResult(
                success=True,
                message=f"Switched playback to {target_device['name']}",
                data={
                    "device_id": target_device["id"],
                    "device_name": target_device["name"],
                    "device_type": target_device["type"]
                }
            )

        except NoActiveDeviceError:
            raise
        except Exception as e:
            logger.error(f"Failed to switch device: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to switch device: {str(e)}", e)


# Import spotify_service singleton
from app.services.spotify import spotify_service

# Create singleton instance
spotify_controller = SpotifyController(spotify_service=spotify_service)
