"""Track playback command handlers for Spotify service."""

import logging
from typing import Any, Optional

from app.services.integrations.spotify.exceptions import (
    NoActiveDeviceError,
    PremiumRequiredError,
    SearchNoResultsError,
    SpotifyAPIError,
)
from app.services.integrations.spotify.models import CommandResult
from app.services.integrations.spotify.helpers.retry import (
    retry_on_transient_error,
)

logger = logging.getLogger(__name__)


class SpotifyTrackCommandsMixin:
    """Search/play and queue command handlers for tracks."""

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def play_track_uri(
        self: Any,
        uri: str,
        access_token: str,
    ) -> CommandResult:
        """Play a track directly by Spotify URI."""
        track_uri = uri.strip()
        if not track_uri:
            raise SearchNoResultsError("track uri", "track")

        try:
            device_id = await self.get_active_device(access_token)
            if not device_id:
                logger.info(
                    "No active device found for URI play; returning client playback action",
                    extra={"uri": track_uri},
                )
                return CommandResult(
                    success=True,
                    message="Got it. Trying playback on your active app.",
                    data={
                        "uri": track_uri,
                        "action_required": "client_playback",
                    },
                )

            await self.client.play(
                access_token=access_token,
                uri=track_uri,
                device_id=device_id,
            )
            return CommandResult(
                success=True,
                message="Now playing your selected track.",
                data={"uri": track_uri},
            )
        except Exception as e:
            logger.error(f"Failed to play URI track: {str(e)}", exc_info=True)
            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing specific tracks requires Spotify Premium",
                    feature="Track playback",
                )
            status_code = self._extract_status_code(e)
            is_retryable = (
                status_code in [429, 500, 502, 503, 504] if status_code else False
            )
            raise SpotifyAPIError(
                "Failed to play selected track",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code,
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def search_and_play_track(
        self: Any,
        query: str,
        access_token: str,
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> CommandResult:
        """Search for a track and play the best candidate."""
        selected_track: Optional[dict[str, Any]] = None

        try:
            selected_track, clarification_result = await self._resolve_track_candidate(
                query=query,
                access_token=access_token,
                artist=artist,
                playlist_name=playlist_name,
            )
            if clarification_result:
                logger.info(
                    "Returning clarification result for track request",
                    extra={
                        "query": query,
                        "artist": artist,
                        "playlist_name": playlist_name,
                    },
                )
                return clarification_result

            if selected_track is None:
                raise SearchNoResultsError(query, "track")

            payload = self._track_payload(selected_track)
            track_uri = str(payload["uri"])
            track_id = str(payload["track_id"])
            track_name = str(payload["track_name"])
            track_artist = str(payload["artist"])

            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            try:
                playback_meta = await self._play_track_queue_first(
                    access_token=access_token,
                    device_id=device_id,
                    track_uri=track_uri,
                    track_id=track_id,
                    track_name=track_name,
                )
            except Exception as play_error:
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing specific tracks requires Spotify Premium",
                        feature="Track playback",
                    )
                raise

            verified = playback_meta.get("verified")
            if verified is False:
                logger.warning(
                    "Track playback command acknowledged but verification mismatch",
                    extra={
                        "requested_track_id": track_id,
                        "requested_track_name": track_name,
                        "queue_first": True,
                    },
                )

            return CommandResult(
                success=True,
                message=f"Now playing '{track_name}' by {track_artist}",
                data={**payload, **playback_meta},
            )

        except NoActiveDeviceError:
            # If no active device is available, return URI for client-side playback.
            if not selected_track:
                raise
            payload = self._track_payload(selected_track)
            logger.info(
                "No active device found in Web API path; returning client playback action",
                extra={
                    "uri": payload.get("uri"),
                    "track_name": payload.get("track_name"),
                },
            )
            return CommandResult(
                success=True,
                message=(
                    f"Found '{payload.get('track_name')}' by "
                    f"{payload.get('artist')}. Trying playback on your active app."
                ),
                data={**payload, "action_required": "client_playback"},
            )

        except (SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play track: {str(e)}", exc_info=True)
            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing specific tracks requires Spotify Premium",
                    feature="Track playback",
                )
            status_code = self._extract_status_code(e)
            is_retryable = (
                status_code in [429, 500, 502, 503, 504] if status_code else False
            )
            raise SpotifyAPIError(
                "Failed to play track",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code,
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def add_to_queue(
        self: Any,
        query: str,
        access_token: str,
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> CommandResult:
        """Search for a track and add it to queue."""
        try:
            selected_track, clarification_result = await self._resolve_track_candidate(
                query=query,
                access_token=access_token,
                artist=artist,
                playlist_name=playlist_name,
            )
            if clarification_result:
                logger.info(
                    "Returning clarification result for add-to-queue request",
                    extra={
                        "query": query,
                        "artist": artist,
                        "playlist_name": playlist_name,
                    },
                )
                return clarification_result
            if selected_track is None:
                raise SearchNoResultsError(query, "track")

            payload = self._track_payload(selected_track)
            device_id = await self.get_active_device(access_token)
            if not device_id:
                raise NoActiveDeviceError()

            try:
                await self.client.add_to_queue(
                    access_token=access_token,
                    uri=str(payload["uri"]),
                    device_id=device_id,
                )
            except Exception as queue_error:
                if self._check_premium_error(queue_error):
                    raise PremiumRequiredError(
                        "Adding to queue requires Spotify Premium",
                        feature="Queue management",
                    )
                raise

            return CommandResult(
                success=True,
                message=f"Added '{payload['track_name']}' by {payload['artist']} to queue.",
                data={**payload, "queued": True},
            )

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to add track to queue: {str(e)}", exc_info=True)
            status_code = self._extract_status_code(e)
            is_retryable = (
                status_code in [429, 500, 502, 503, 504] if status_code else False
            )
            raise SpotifyAPIError(
                "Failed to add track to queue",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code,
            )
