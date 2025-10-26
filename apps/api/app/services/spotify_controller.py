"""Spotify Controller for voice command execution."""
import asyncio
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Optional, TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)


# ============================================================================
# Retry Decorator
# ============================================================================


def retry_on_transient_error(max_retries: int = 2, delay: float = 1.0):
    """Decorator to retry operations on transient errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay in seconds between retries
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except SpotifyAPIError as e:
                    last_error = e
                    
                    # Only retry if error is marked as retryable
                    if not e.is_retryable or attempt >= max_retries:
                        raise
                    
                    # Log retry attempt
                    logger.warning(
                        f"Transient error in {func.__name__}, "
                        f"attempt {attempt + 1}/{max_retries + 1}: {str(e)}"
                    )
                    
                    # Wait before retrying (exponential backoff)
                    wait_time = delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                
                except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError, AuthenticationError):
                    # Don't retry these errors
                    raise
                
                except Exception as e:
                    # For unknown errors, don't retry
                    last_error = e
                    raise
            
            # If we get here, all retries failed
            if last_error:
                raise last_error
        
        return wrapper
    return decorator


# ============================================================================
# Custom Exceptions
# ============================================================================


class SpotifyControllerError(Exception):
    """Base exception for SpotifyController errors."""
    
    def __init__(self, message: str, error_code: str = "SPOTIFY_ERROR", suggestions: Optional[list[str]] = None):
        """Initialize error with message, code, and optional suggestions.
        
        Args:
            message: User-friendly error message
            error_code: Machine-readable error code
            suggestions: Optional list of suggestions for the user
        """
        self.message = message
        self.error_code = error_code
        self.suggestions = suggestions or []
        super().__init__(self.message)


class NoActiveDeviceError(SpotifyControllerError):
    """Raised when no active Spotify device is found."""
    
    def __init__(
        self,
        message: str = "No active Spotify device found. Please open Spotify on a device.",
        available_devices: Optional[list[str]] = None
    ):
        """Initialize with message and optional list of available devices.
        
        Args:
            message: User-friendly error message
            available_devices: Optional list of available device names
        """
        suggestions = []
        if available_devices:
            suggestions = [
                f"Try opening Spotify on: {', '.join(available_devices)}",
                "Make sure Spotify is running on at least one device"
            ]
        else:
            suggestions = [
                "Open Spotify on your phone, computer, or speaker",
                "Make sure the device is connected to the internet",
                "Try refreshing your Spotify app"
            ]
        
        super().__init__(message, "NO_DEVICE", suggestions)
        self.available_devices = available_devices or []


class SearchNoResultsError(SpotifyControllerError):
    """Raised when search returns no results."""
    
    def __init__(
        self,
        query: str,
        search_type: str = "track",
        suggestions: Optional[list[str]] = None
    ):
        """Initialize with query, search type, and optional suggestions.
        
        Args:
            query: The search query that returned no results
            search_type: Type of content searched (track, album, playlist, artist)
            suggestions: Optional list of alternative suggestions
        """
        message = f"Couldn't find {search_type} '{query}'"
        
        # Generate helpful suggestions
        default_suggestions = [
            "Try being more specific with the name",
            "Check the spelling",
            f"Try including the artist name for {search_type}s"
        ]
        
        if search_type == "playlist":
            default_suggestions = [
                "Try searching for a different playlist",
                "Make sure the playlist name is spelled correctly",
                "Try creating the playlist first in Spotify"
            ]
        
        super().__init__(
            message,
            "NO_RESULTS",
            suggestions or default_suggestions
        )
        self.query = query
        self.search_type = search_type


class SpotifyAPIError(SpotifyControllerError):
    """Raised when Spotify API call fails."""
    
    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        is_retryable: bool = False,
        status_code: Optional[int] = None
    ):
        """Initialize with message, original error, and retry information.
        
        Args:
            message: User-friendly error message
            original_error: The original exception that caused this error
            is_retryable: Whether the operation can be retried
            status_code: HTTP status code if applicable
        """
        suggestions = []
        
        # Provide context-specific suggestions based on status code
        if status_code == 429:
            suggestions = [
                "Spotify is rate limiting requests",
                "Please wait a moment and try again"
            ]
            is_retryable = True
        elif status_code == 503:
            suggestions = [
                "Spotify service is temporarily unavailable",
                "Please try again in a few moments"
            ]
            is_retryable = True
        elif status_code in [500, 502, 504]:
            suggestions = [
                "Spotify is experiencing technical difficulties",
                "Please try again later"
            ]
            is_retryable = True
        elif is_retryable:
            suggestions = ["Please try your command again"]
        else:
            suggestions = [
                "Check your internet connection",
                "Try reconnecting Spotify in settings"
            ]
        
        super().__init__(message, "API_ERROR", suggestions)
        self.original_error = original_error
        self.is_retryable = is_retryable
        self.status_code = status_code


class PremiumRequiredError(SpotifyControllerError):
    """Raised when operation requires Spotify Premium."""
    
    def __init__(
        self,
        message: str = "This feature requires Spotify Premium",
        feature: Optional[str] = None
    ):
        """Initialize with message and optional feature name.
        
        Args:
            message: User-friendly error message
            feature: The specific feature that requires premium
        """
        suggestions = [
            "Upgrade to Spotify Premium to use this feature",
            "Try using the Spotify app directly for free tier features"
        ]
        
        if feature:
            message = f"{feature} requires Spotify Premium"
        
        super().__init__(message, "PREMIUM_REQUIRED", suggestions)
        self.feature = feature


class AuthenticationError(SpotifyControllerError):
    """Raised when authentication fails."""
    
    def __init__(
        self,
        message: str = "Failed to authenticate with Spotify",
        reason: Optional[str] = None
    ):
        """Initialize with message and optional reason.
        
        Args:
            message: User-friendly error message
            reason: Optional reason for authentication failure
        """
        suggestions = [
            "Try reconnecting Spotify in settings",
            "Make sure you're logged into Spotify",
            "Check that you've granted the necessary permissions"
        ]
        
        if reason == "token_expired":
            message = "Your Spotify session has expired"
            suggestions = [
                "Please reconnect Spotify in settings",
                "This usually happens after being logged out"
            ]
        elif reason == "no_integration":
            message = "Spotify is not connected"
            suggestions = [
                "Connect Spotify in the app settings",
                "Make sure you complete the Spotify authorization"
            ]
        elif reason == "refresh_failed":
            message = "Failed to refresh your Spotify session"
            suggestions = [
                "Please reconnect Spotify in settings",
                "You may need to log out and log back in"
            ]
        
        super().__init__(message, "AUTH_ERROR", suggestions)
        self.reason = reason


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
    
    def _check_premium_error(self, error: Exception) -> bool:
        """Check if error indicates premium requirement.
        
        Args:
            error: Exception to check
            
        Returns:
            True if error indicates premium is required
        """
        error_str = str(error).lower()
        premium_indicators = [
            "premium",
            "premium required",
            "requires premium",
            "player command failed: premium required",
            "restriction",
            "restricted"
        ]
        return any(indicator in error_str for indicator in premium_indicators)
    
    def _extract_status_code(self, error: Exception) -> Optional[int]:
        """Extract HTTP status code from exception.
        
        Args:
            error: Exception to extract status code from
            
        Returns:
            Status code if found, None otherwise
        """
        # Try different ways to get status code
        if hasattr(error, 'status_code'):
            return error.status_code
        if hasattr(error, 'response') and hasattr(error.response, 'status_code'):
            return error.response.status_code
        
        # Try to parse from error message
        error_str = str(error)
        if 'status code' in error_str.lower():
            import re
            match = re.search(r'status code[:\s]+(\d+)', error_str, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return None

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
            # Check if it's an HTTP error with status code
            status_code = getattr(e, 'status_code', None)
            if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                status_code = e.response.status_code
            
            raise SpotifyAPIError(
                "Failed to get device information",
                original_error=e,
                is_retryable=status_code in [429, 500, 502, 503, 504] if status_code else False,
                status_code=status_code
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
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
            PremiumRequiredError: If premium is required
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
                # Generate helpful suggestions based on query
                suggestions = []
                if len(query) < 3:
                    suggestions.append("Try using a longer search term")
                if not artist:
                    suggestions.append("Try including the artist name")
                suggestions.append("Check the spelling of the track name")
                
                raise SearchNoResultsError(query, "track", suggestions)

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
                # Get available devices for better error message
                try:
                    devices_response = await self.spotify.get_available_devices(access_token)
                    devices = devices_response.get("devices", [])
                    device_names = [d.get("name") for d in devices if d.get("name")]
                    raise NoActiveDeviceError(available_devices=device_names)
                except NoActiveDeviceError:
                    raise
                except Exception:
                    raise NoActiveDeviceError()

            # Play the track
            try:
                await self.spotify.play(
                    access_token=access_token,
                    uri=track_uri,
                    device_id=device_id
                )
            except Exception as play_error:
                # Check if it's a premium requirement error
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing specific tracks requires Spotify Premium",
                        feature="Track playback"
                    )
                raise

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

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play track: {str(e)}", exc_info=True)
            
            # Check for premium requirement
            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing specific tracks requires Spotify Premium",
                    feature="Track playback"
                )
            
            # Extract status code and determine if retryable
            status_code = self._extract_status_code(e)
            is_retryable = status_code in [429, 500, 502, 503, 504] if status_code else False
            
            raise SpotifyAPIError(
                "Failed to play track",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
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
            PremiumRequiredError: If premium is required
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
                suggestions = [
                    "Check the spelling of the playlist name",
                    "Try searching for a different playlist"
                ]
                if user_playlists_only:
                    suggestions.append("Make sure the playlist exists in your library")
                raise SearchNoResultsError(query, "playlist", suggestions)

            # Select first matching playlist
            selected_playlist = playlists[0]
            playlist_name = selected_playlist["name"]
            playlist_uri = selected_playlist["uri"]
            playlist_id = selected_playlist["id"]

            logger.info(f"Selected playlist: {playlist_name}")

            # Get active device
            device_id = await self.get_active_device(access_token)
            if not device_id:
                try:
                    devices_response = await self.spotify.get_available_devices(access_token)
                    devices = devices_response.get("devices", [])
                    device_names = [d.get("name") for d in devices if d.get("name")]
                    raise NoActiveDeviceError(available_devices=device_names)
                except NoActiveDeviceError:
                    raise
                except Exception:
                    raise NoActiveDeviceError()

            # Play the playlist
            try:
                await self.spotify.play(
                    access_token=access_token,
                    uri=playlist_uri,
                    device_id=device_id
                )
            except Exception as play_error:
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing playlists requires Spotify Premium",
                        feature="Playlist playback"
                    )
                raise

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

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play playlist: {str(e)}", exc_info=True)
            
            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing playlists requires Spotify Premium",
                    feature="Playlist playback"
                )
            
            status_code = self._extract_status_code(e)
            is_retryable = status_code in [429, 500, 502, 503, 504] if status_code else False
            
            raise SpotifyAPIError(
                "Failed to play playlist",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
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
            PremiumRequiredError: If premium is required
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
                suggestions = [
                    "Check the spelling of the album name"
                ]
                if not artist:
                    suggestions.append("Try including the artist name")
                suggestions.append("Make sure the album is available on Spotify")
                
                raise SearchNoResultsError(query, "album", suggestions)

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
                try:
                    devices_response = await self.spotify.get_available_devices(access_token)
                    devices = devices_response.get("devices", [])
                    device_names = [d.get("name") for d in devices if d.get("name")]
                    raise NoActiveDeviceError(available_devices=device_names)
                except NoActiveDeviceError:
                    raise
                except Exception:
                    raise NoActiveDeviceError()

            # Play the album
            try:
                await self.spotify.play(
                    access_token=access_token,
                    uri=album_uri,
                    device_id=device_id
                )
            except Exception as play_error:
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing albums requires Spotify Premium",
                        feature="Album playback"
                    )
                raise

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

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play album: {str(e)}", exc_info=True)
            
            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing albums requires Spotify Premium",
                    feature="Album playback"
                )
            
            status_code = self._extract_status_code(e)
            is_retryable = status_code in [429, 500, 502, 503, 504] if status_code else False
            
            raise SpotifyAPIError(
                "Failed to play album",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code
            )

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
