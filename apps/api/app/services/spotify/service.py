"""Spotify service for high-level command orchestration."""

import asyncio
import logging
import re
from difflib import SequenceMatcher
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, Optional

from sqlalchemy.orm import Session

from app.models.integration import Integration
from app.services.spotify.client import SpotifyClient
from app.services.spotify.exceptions import (
    AuthenticationError,
    NoActiveDeviceError,
    PremiumRequiredError,
    SearchNoResultsError,
    SpotifyAPIError,
)
from app.services.spotify.models import CommandResult

if TYPE_CHECKING:
    from app.services.spotify.client import SpotifyClient

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
                    wait_time = delay * (2**attempt)
                    await asyncio.sleep(wait_time)

                except (
                    NoActiveDeviceError,
                    SearchNoResultsError,
                    PremiumRequiredError,
                    AuthenticationError,
                ):
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
# Spotify Service
# ============================================================================


class SpotifyService:
    """High-level service for executing Spotify commands from voice agent."""

    TRACK_CONFIDENCE_MIN = 0.62
    TRACK_CONFIDENCE_GAP = 0.08

    def __init__(self, client: Optional["SpotifyClient"] = None) -> None:
        """Initialize SpotifyService.

        Args:
            client: SpotifyClient instance for API calls (defaults to singleton)
        """
        self.client = client or spotify_client

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
        """Get a valid Spotify access token using the client helper."""
        return await self.client.get_valid_token(integration, db)

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
            "restricted",
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
        if hasattr(error, "status_code"):
            return error.status_code
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            return error.response.status_code

        # Try to parse from error message
        error_str = str(error)
        if "status code" in error_str.lower():
            match = re.search(r"status code[:\s]+(\d+)", error_str, re.IGNORECASE)
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
            # Use available devices list (includes active device) to avoid extra API call.
            devices_response = await self.client.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            if not devices:
                logger.debug("No devices available")
                return None

            # Filter out restricted devices
            valid_devices = [d for d in devices if not d.get("is_restricted", False)]

            if not valid_devices:
                logger.debug("All available devices are restricted")
                # Fallback to all devices but log warning, in case user wants to try anyway
                valid_devices = devices

            # Prefer active device
            for device in valid_devices:
                if device.get("is_active"):
                    logger.info(f"Found active device: {device['name']}")
                    return device["id"]

            # Use first available valid device
            first_device = valid_devices[0]
            logger.info(f"Using first available device: {first_device['name']}")
            return first_device["id"]

        except Exception as e:
            logger.error(f"Failed to get active device: {str(e)}")
            # Check if it's an HTTP error with status code
            status_code = getattr(e, "status_code", None)
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                status_code = e.response.status_code

            raise SpotifyAPIError(
                "Failed to get device information",
                original_error=e,
                is_retryable=status_code in [429, 500, 502, 503, 504]
                if status_code
                else False,
                status_code=status_code,
            )

    def _normalize_match_text(self, value: str) -> str:
        """Normalize text for similarity and token overlap checks."""
        normalized = value.lower().strip()
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _similarity_score(self, left: str, right: str) -> float:
        """Return a fuzzy similarity score in [0, 1]."""
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _token_overlap(self, left: str, right: str) -> float:
        """Return token overlap score in [0, 1]."""
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _is_remix_track(self, track: dict[str, Any]) -> bool:
        """Check whether a track appears to be a remix cut."""
        name = str(track.get("name", "")).lower()
        album = str(track.get("album", {}).get("name", "")).lower()
        return "remix" in name or "remix" in album

    def _rank_track_candidates(
        self,
        tracks: list[dict[str, Any]],
        query: str,
        artist: Optional[str] = None,
        prefer_non_remix: bool = False,
        playlist_boost: float = 0.0,
    ) -> list[tuple[dict[str, Any], float]]:
        """Rank track candidates using a weighted relevance score."""
        normalized_query = self._normalize_match_text(query)
        normalized_artist = self._normalize_match_text(artist or "")
        ranked: list[tuple[dict[str, Any], float]] = []

        for track in tracks:
            track_name = str(track.get("name", ""))
            if not track_name:
                continue

            track_name_norm = self._normalize_match_text(track_name)
            artists_data = track.get("artists", [])
            artist_names = [
                str(item.get("name", ""))
                for item in artists_data
                if isinstance(item, dict) and item.get("name")
            ]
            artists_norm = self._normalize_match_text(" ".join(artist_names))

            title_similarity = self._similarity_score(normalized_query, track_name_norm)
            title_overlap = self._token_overlap(normalized_query, track_name_norm)
            contains_bonus = (
                1.0
                if normalized_query and normalized_query in track_name_norm
                else 0.0
            )
            exact_title_bonus = 1.0 if normalized_query == track_name_norm else 0.0

            artist_similarity = 0.0
            if normalized_artist:
                artist_similarity = self._similarity_score(
                    normalized_artist, artists_norm
                )

            popularity = max(0.0, min(float(track.get("popularity", 0)) / 100.0, 1.0))

            score = (
                (title_similarity * 0.45)
                + (title_overlap * 0.22)
                + (contains_bonus * 0.10)
                + (exact_title_bonus * 0.13)
                + (popularity * 0.10)
            )

            if normalized_artist:
                score += artist_similarity * 0.18
                if artist_similarity >= 0.9:
                    score += 0.08

            if prefer_non_remix and self._is_remix_track(track):
                score -= 0.20

            score += playlist_boost
            score = max(0.0, min(score, 1.5))
            ranked.append((track, score))

            logger.debug(
                "Track candidate ranked",
                extra={
                    "track_name": track_name,
                    "artists": artist_names[:2],
                    "score": round(score, 4),
                    "title_similarity": round(title_similarity, 4),
                    "title_overlap": round(title_overlap, 4),
                    "artist_similarity": round(artist_similarity, 4),
                    "popularity": round(popularity, 4),
                    "playlist_boost": round(playlist_boost, 4),
                },
            )

        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    def _format_track_option(self, track: dict[str, Any]) -> str:
        """Format a human-readable track label."""
        name = str(track.get("name", "Unknown track"))
        artists = track.get("artists", [])
        artist_name = "Unknown artist"
        if isinstance(artists, list) and artists:
            first = artists[0]
            if isinstance(first, dict):
                artist_name = str(first.get("name", artist_name))
        return f"{name} by {artist_name}"

    def _is_ambiguous_track_match(
        self, ranked_tracks: list[tuple[dict[str, Any], float]]
    ) -> bool:
        """Return True when top candidates are too close to auto-select safely."""
        if len(ranked_tracks) < 2:
            return False
        top_score = ranked_tracks[0][1]
        second_score = ranked_tracks[1][1]
        gap = top_score - second_score
        return top_score < self.TRACK_CONFIDENCE_MIN or gap < self.TRACK_CONFIDENCE_GAP

    def _build_clarification_result(
        self,
        query: str,
        ranked_tracks: list[tuple[dict[str, Any], float]],
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> CommandResult:
        """Create a clarification response when match confidence is low."""
        options = [
            self._format_track_option(track) for track, _ in ranked_tracks[:3]
        ]
        base_message = f"I found multiple matches for '{query}'."
        if artist:
            base_message = f"I found multiple matches for '{query}' by '{artist}'."
        if playlist_name:
            base_message = (
                f"I checked playlist '{playlist_name}' first, but I still found "
                f"multiple close matches for '{query}'."
            )
        options_text = ", ".join(options) if options else "No close matches available."
        message = f"{base_message} Did you mean: {options_text}?"
        return CommandResult(
            success=True,
            message=message,
            data={
                "requires_clarification": True,
                "query": query,
                "artist": artist,
                "playlist_name": playlist_name,
                "options": options,
            },
        )

    async def _collect_user_playlists(
        self, access_token: str, max_playlists: int = 200
    ) -> list[dict[str, Any]]:
        """Fetch user playlists with pagination support."""
        playlists: list[dict[str, Any]] = []
        offset = 0
        page_size = 50

        while len(playlists) < max_playlists:
            response = await self.client.get_user_playlists(
                access_token=access_token, limit=page_size, offset=offset
            )
            items = response.get("items", [])
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if isinstance(item, dict):
                    playlists.append(item)
                    if len(playlists) >= max_playlists:
                        break

            if len(items) < page_size:
                break
            offset += page_size

        logger.info(
            "Fetched user playlists",
            extra={"playlists_count": len(playlists)},
        )
        return playlists

    async def _resolve_track_candidate(
        self,
        query: str,
        access_token: str,
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[CommandResult]]:
        """Resolve the best track candidate or return a clarification result."""
        raw_query = query.strip()
        lowered_query = raw_query.lower()
        prefer_non_remix = any(
            token in lowered_query for token in ["not the remix", "not remix", "no remix"]
        )
        cleaned_query = re.sub(
            r"\bnot\s+(?:the\s+)?remix\b", "", raw_query, flags=re.IGNORECASE
        )
        cleaned_query = re.sub(r"\bno\s+remix\b", "", cleaned_query, flags=re.IGNORECASE)
        cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()
        effective_query = cleaned_query or raw_query

        ranked_candidates: list[tuple[dict[str, Any], float]] = []

        # If user asks for a track from a playlist, search that playlist first.
        if playlist_name:
            logger.info(
                "Searching for track in requested playlist first",
                extra={"playlist_name": playlist_name, "query": effective_query},
            )
            user_playlists = await self._collect_user_playlists(access_token)
            playlist_norm = self._normalize_match_text(playlist_name)
            selected_playlist: Optional[dict[str, Any]] = None
            best_playlist_score = 0.0

            for playlist in user_playlists:
                candidate_name = str(playlist.get("name", ""))
                candidate_norm = self._normalize_match_text(candidate_name)
                if not candidate_norm:
                    continue
                similarity = self._similarity_score(playlist_norm, candidate_norm)
                if playlist_norm == candidate_norm:
                    similarity += 0.20
                elif playlist_norm in candidate_norm:
                    similarity += 0.10
                if similarity > best_playlist_score:
                    selected_playlist = playlist
                    best_playlist_score = similarity

            if selected_playlist and best_playlist_score >= 0.60:
                playlist_id = str(selected_playlist.get("id", ""))
                playlist_tracks_rows = await self.client.get_playlist_tracks(
                    access_token=access_token,
                    playlist_id=playlist_id,
                    max_items=250,
                )
                playlist_tracks: list[dict[str, Any]] = []
                for row in playlist_tracks_rows:
                    if isinstance(row, dict):
                        track = row.get("track")
                        if isinstance(track, dict):
                            playlist_tracks.append(track)

                playlist_ranked = self._rank_track_candidates(
                    playlist_tracks,
                    query=effective_query,
                    artist=artist,
                    prefer_non_remix=prefer_non_remix,
                    playlist_boost=0.12,
                )
                ranked_candidates.extend(playlist_ranked)
                logger.info(
                    "Ranked candidates from playlist",
                    extra={
                        "playlist_name": selected_playlist.get("name"),
                        "playlist_tracks": len(playlist_tracks),
                        "ranked_candidates": len(playlist_ranked),
                    },
                )
            else:
                logger.warning(
                    "Requested playlist was not confidently matched in user library",
                    extra={"playlist_name": playlist_name},
                )

        # Global track search remains the default path for generic play-song requests.
        search_query = effective_query
        if artist:
            search_query = f"track:{effective_query} artist:{artist}"

        logger.info("Searching Spotify catalog for track", extra={"query": search_query})
        search_results = await self.client.search(
            access_token=access_token, query=search_query, types="track", limit=25
        )

        global_tracks = search_results.get("tracks", {}).get("items", [])
        if not global_tracks and artist and effective_query:
            # Retry without the artist qualifier to avoid over-constraining.
            logger.info(
                "Retrying track search without artist qualifier",
                extra={"query": effective_query, "artist": artist},
            )
            search_results = await self.client.search(
                access_token=access_token, query=effective_query, types="track", limit=25
            )
            global_tracks = search_results.get("tracks", {}).get("items", [])

        if isinstance(global_tracks, list) and global_tracks:
            ranked_candidates.extend(
                self._rank_track_candidates(
                    tracks=[item for item in global_tracks if isinstance(item, dict)],
                    query=effective_query,
                    artist=artist,
                    prefer_non_remix=prefer_non_remix,
                    playlist_boost=0.0,
                )
            )

        if not ranked_candidates:
            suggestions = []
            if len(effective_query) < 3:
                suggestions.append("Try using a longer search term")
            if not artist:
                suggestions.append("Try including the artist name")
            suggestions.append("Check the spelling of the track name")
            raise SearchNoResultsError(effective_query, "track", suggestions)

        # Deduplicate by track id/uri while keeping best score per track.
        deduped: dict[str, tuple[dict[str, Any], float]] = {}
        for track, score in ranked_candidates:
            key = str(track.get("id") or track.get("uri") or track.get("name", ""))
            if not key:
                continue
            existing = deduped.get(key)
            if existing is None or score > existing[1]:
                deduped[key] = (track, score)
        final_ranked = sorted(deduped.values(), key=lambda item: item[1], reverse=True)

        logger.info(
            "Resolved ranked track candidates",
            extra={
                "query": effective_query,
                "artist": artist,
                "playlist_name": playlist_name,
                "candidate_count": len(final_ranked),
                "top_score": round(final_ranked[0][1], 4) if final_ranked else None,
            },
        )

        if not final_ranked:
            raise SearchNoResultsError(effective_query, "track")

        if self._is_ambiguous_track_match(final_ranked):
            return None, self._build_clarification_result(
                query=effective_query,
                ranked_tracks=final_ranked,
                artist=artist,
                playlist_name=playlist_name,
            )

        top_track, top_score = final_ranked[0]
        if top_score < self.TRACK_CONFIDENCE_MIN:
            return None, self._build_clarification_result(
                query=effective_query,
                ranked_tracks=final_ranked,
                artist=artist,
                playlist_name=playlist_name,
            )

        logger.info(
            "Selected top track candidate",
            extra={
                "track_name": top_track.get("name"),
                "artists": top_track.get("artists"),
                "score": round(top_score, 4),
            },
        )
        return top_track, None

    def _track_payload(self, track: dict[str, Any]) -> dict[str, Any]:
        """Build consistent track payload for downstream consumers."""
        artists = track.get("artists", [])
        track_artist = ""
        if isinstance(artists, list) and artists:
            first = artists[0]
            if isinstance(first, dict):
                track_artist = str(first.get("name", ""))
        track_uri = str(track.get("uri", ""))
        track_id = str(track.get("id", ""))
        album = track.get("album", {})
        album_name = ""
        album_art = None
        if isinstance(album, dict):
            album_name = str(album.get("name", ""))
            images = album.get("images", [])
            if isinstance(images, list) and images:
                first_image = images[0]
                if isinstance(first_image, dict):
                    album_art = first_image.get("url")
        return {
            "track_name": str(track.get("name", "")),
            "artist": track_artist,
            "album": album_name,
            "uri": track_uri,
            "track_id": track_id,
            "album_art": album_art,
        }

    async def _verify_playback_track(
        self, access_token: str, expected_track_id: str
    ) -> Optional[bool]:
        """Best-effort verification for playback state after play/skip commands."""
        if not expected_track_id:
            return None
        try:
            await asyncio.sleep(0.35)
            playback = await self.client.get_current_playback(access_token)
            current_track_id = str(playback.get("item", {}).get("id", ""))
            if not current_track_id:
                return None
            return current_track_id == expected_track_id
        except Exception as exc:
            logger.warning(
                "Playback verification failed",
                extra={"expected_track_id": expected_track_id, "error": str(exc)},
            )
            return None

    async def _verify_track_changed(
        self, access_token: str, previous_track_id: str
    ) -> Optional[bool]:
        """Best-effort check that current playback is not the previous track."""
        if not previous_track_id:
            return None
        try:
            await asyncio.sleep(0.35)
            playback = await self.client.get_current_playback(access_token)
            current_track_id = str(playback.get("item", {}).get("id", ""))
            if not current_track_id:
                return None
            return current_track_id != previous_track_id
        except Exception as exc:
            logger.warning(
                "Track-change verification failed",
                extra={"previous_track_id": previous_track_id, "error": str(exc)},
            )
            return None

    async def _play_track_queue_first(
        self,
        *,
        access_token: str,
        device_id: str,
        track_uri: str,
        track_id: str,
        track_name: str,
    ) -> dict[str, Any]:
        """Execute a queue-first playback strategy with stall recovery.

        Strategy:
        1) Add track to queue.
        2) If playback is active, skip next to advance to queued track.
        3) If no active playback context, cold-start with direct play.
        4) Verify expected track and recover with direct play on mismatch.
        """
        had_playback_context = False
        previous_track_id = ""
        queue_advanced = False
        direct_play_used = False

        try:
            current_playback = await self.client.get_current_playback(access_token)
            previous_track_id = str(current_playback.get("item", {}).get("id", ""))
            is_playing_now = bool(current_playback.get("is_playing", False))
            had_playback_context = bool(previous_track_id) or is_playing_now
        except Exception as exc:
            logger.warning(
                "Unable to snapshot playback before queue-first play",
                extra={"error": str(exc), "track_name": track_name},
            )

        logger.info(
            "Queue-first playback: adding track to queue",
            extra={
                "track_name": track_name,
                "track_id": track_id,
                "device_id": device_id,
                "had_playback_context": had_playback_context,
            },
        )
        await self.client.add_to_queue(
            access_token=access_token,
            uri=track_uri,
            device_id=device_id,
        )

        if had_playback_context:
            try:
                await self.client.skip_next(access_token=access_token, device_id=device_id)
                queue_advanced = True
                logger.info(
                    "Queue-first playback advanced with skip-next",
                    extra={"track_name": track_name, "device_id": device_id},
                )
            except Exception as exc:
                logger.warning(
                    "Queue-first skip-next failed; falling back to direct play",
                    extra={"error": str(exc), "track_name": track_name},
                )
                await self.client.play(
                    access_token=access_token, uri=track_uri, device_id=device_id
                )
                direct_play_used = True
        else:
            logger.info(
                "Queue-first detected cold start; using direct play bootstrap",
                extra={"track_name": track_name, "device_id": device_id},
            )
            await self.client.play(access_token=access_token, uri=track_uri, device_id=device_id)
            direct_play_used = True

        verified = await self._verify_playback_track(access_token, track_id)
        stalled_recovery_used = False

        if verified is False and not direct_play_used:
            logger.warning(
                "Queue-first verification mismatch; attempting direct-play recovery",
                extra={"track_name": track_name, "track_id": track_id},
            )
            await self.client.play(access_token=access_token, uri=track_uri, device_id=device_id)
            direct_play_used = True
            stalled_recovery_used = True
            verified = await self._verify_playback_track(access_token, track_id)

        return {
            "queue_first": True,
            "queue_advanced": queue_advanced,
            "direct_play_used": direct_play_used,
            "stalled_recovery_used": stalled_recovery_used,
            "previous_track_id": previous_track_id or None,
            "verified": verified,
        }

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def search_and_play_track(
        self,
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
                    extra={"query": query, "artist": artist, "playlist_name": playlist_name},
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
                extra={"uri": payload.get("uri"), "track_name": payload.get("track_name")},
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
        self,
        query: str,
        access_token: str,
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> CommandResult:
        """Search for a track and add it to queue."""
        selected_track, clarification_result = await self._resolve_track_candidate(
            query=query,
            access_token=access_token,
            artist=artist,
            playlist_name=playlist_name,
        )
        if clarification_result:
            return clarification_result
        if selected_track is None:
            raise SearchNoResultsError(query, "track")

        payload = self._track_payload(selected_track)
        device_id = await self.get_active_device(access_token)
        if not device_id:
            raise NoActiveDeviceError()

        await self.client.add_to_queue(
            access_token=access_token,
            uri=str(payload["uri"]),
            device_id=device_id,
        )
        return CommandResult(
            success=True,
            message=f"Added '{payload['track_name']}' by {payload['artist']} to queue.",
            data={**payload, "queued": True},
        )

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def search_and_play_playlist(
        self, query: str, access_token: str, user_playlists_only: bool = False
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
            logger.info(
                f"Searching for playlist: {query} (user_only={user_playlists_only})"
            )

            playlists = []

            if user_playlists_only:
                # Search user's playlists
                user_playlists_response = await self.client.get_user_playlists(
                    access_token=access_token, limit=50
                )
                all_playlists = user_playlists_response.get("items", [])

                # Filter by query (case-insensitive)
                query_lower = query.lower()
                playlists = [
                    p for p in all_playlists if query_lower in p["name"].lower()
                ]
            else:
                # Search all playlists
                search_results = await self.client.search(
                    access_token=access_token, query=query, types="playlist", limit=10
                )
                playlists = search_results.get("playlists", {}).get("items", [])

            if not playlists:
                suggestions = [
                    "Check the spelling of the playlist name",
                    "Try searching for a different playlist",
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
                raise NoActiveDeviceError()

            # Play the playlist
            try:
                await self.client.play(
                    access_token=access_token, uri=playlist_uri, device_id=device_id
                )
            except Exception as play_error:
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing playlists requires Spotify Premium",
                        feature="Playlist playback",
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
                    "tracks_total": selected_playlist.get("tracks", {}).get("total", 0),
                },
            )

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play playlist: {str(e)}", exc_info=True)

            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing playlists requires Spotify Premium",
                    feature="Playlist playback",
                )

            status_code = self._extract_status_code(e)
            is_retryable = (
                status_code in [429, 500, 502, 503, 504] if status_code else False
            )

            raise SpotifyAPIError(
                "Failed to play playlist",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code,
            )

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def search_and_play_album(
        self, query: str, access_token: str, artist: Optional[str] = None
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
            search_results = await self.client.search(
                access_token=access_token, query=search_query, types="album", limit=10
            )

            albums = search_results.get("albums", {}).get("items", [])
            if not albums:
                suggestions = ["Check the spelling of the album name"]
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
                raise NoActiveDeviceError()

            # Play the album
            try:
                await self.client.play(
                    access_token=access_token, uri=album_uri, device_id=device_id
                )
            except Exception as play_error:
                if self._check_premium_error(play_error):
                    raise PremiumRequiredError(
                        "Playing albums requires Spotify Premium",
                        feature="Album playback",
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
                    "album_art": selected_album.get("images", [{}])[0].get("url")
                    if selected_album.get("images")
                    else None,
                },
            )

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error(f"Failed to search and play album: {str(e)}", exc_info=True)

            if self._check_premium_error(e):
                raise PremiumRequiredError(
                    "Playing albums requires Spotify Premium", feature="Album playback"
                )

            status_code = self._extract_status_code(e)
            is_retryable = (
                status_code in [429, 500, 502, 503, 504] if status_code else False
            )

            raise SpotifyAPIError(
                "Failed to play album",
                original_error=e,
                is_retryable=is_retryable,
                status_code=status_code,
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

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Pause requested. Client playback fallback will handle it.",
                    data={"action_required": "client_playback", "action": "pause"},
                )

            await self.client.pause(access_token=access_token, device_id=device_id)

            return CommandResult(success=True, message="Paused playback.", data={})

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
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Resume requested. Client playback fallback will handle it.",
                    data={"action_required": "client_playback", "action": "resume"},
                )

            await self.client.play(access_token=access_token, device_id=device_id)

            return CommandResult(success=True, message="Resumed playback.", data={})

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
            previous_track_id: Optional[str] = None
            try:
                current_playback = await self.client.get_current_playback(access_token)
                previous_track_id = str(current_playback.get("item", {}).get("id", ""))
            except Exception as exc:
                logger.warning(
                    "Failed to snapshot playback before skipping next",
                    extra={"error": str(exc)},
                )

            device_id = await self.get_active_device(access_token)

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Next requested - client should handle",
                    data={"action_required": "client_playback", "action": "next"},
                )

            await self.client.skip_next(access_token=access_token, device_id=device_id)

            verified = await self._verify_track_changed(
                access_token=access_token,
                previous_track_id=previous_track_id or "",
            )
            if verified is False:
                logger.warning(
                    "Next-track verification indicates playback may not have changed",
                    extra={"previous_track_id": previous_track_id},
                )
                return CommandResult(
                    success=True,
                    message=(
                        "Sent next-track command, but I could not confirm a track change. "
                        "Check the active Spotify device."
                    ),
                    data={"verified": False, "previous_track_id": previous_track_id},
                )

            return CommandResult(
                success=True,
                message="Skipped to the next track.",
                data={"verified": verified, "previous_track_id": previous_track_id},
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
            previous_track_id: Optional[str] = None
            try:
                current_playback = await self.client.get_current_playback(access_token)
                previous_track_id = str(current_playback.get("item", {}).get("id", ""))
            except Exception as exc:
                logger.warning(
                    "Failed to snapshot playback before skipping previous",
                    extra={"error": str(exc)},
                )

            device_id = await self.get_active_device(access_token)

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Previous requested - client should handle",
                    data={"action_required": "client_playback", "action": "previous"},
                )

            await self.client.skip_previous(
                access_token=access_token, device_id=device_id
            )

            verified = await self._verify_track_changed(
                access_token=access_token,
                previous_track_id=previous_track_id or "",
            )
            if verified is False:
                logger.warning(
                    "Previous-track verification indicates playback may not have changed",
                    extra={"previous_track_id": previous_track_id},
                )
                return CommandResult(
                    success=True,
                    message=(
                        "Sent previous-track command, but I could not confirm a track change. "
                        "Check the active Spotify device."
                    ),
                    data={"verified": False, "previous_track_id": previous_track_id},
                )

            return CommandResult(
                success=True,
                message="Went back to the previous track.",
                data={"verified": verified, "previous_track_id": previous_track_id},
            )

        except Exception as e:
            logger.error(f"Failed to skip back: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to skip back: {str(e)}", e)

    async def set_volume(self, access_token: str, volume_percent: int) -> CommandResult:
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

            await self.client.set_volume(
                access_token=access_token,
                volume_percent=volume_percent,
                device_id=device_id,
            )

            return CommandResult(
                success=True,
                message=f"Volume set to {volume_percent}%",
                data={"volume": volume_percent},
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

            devices_response = await self.client.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            device_list = [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "type": d["type"],
                    "is_active": d.get("is_active", False),
                    "volume_percent": d.get("volume_percent", 0),
                }
                for d in devices
            ]

            if not devices:
                message = "No devices available"
            else:
                device_names = [d["name"] for d in device_list]
                message = f"Available devices: {', '.join(device_names)}"

            return CommandResult(
                success=True, message=message, data={"devices": device_list}
            )

        except Exception as e:
            logger.error(f"Failed to get devices: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to get devices: {str(e)}", e)

    async def switch_device(
        self,
        access_token: str,
        device_name: Optional[str] = None,
        device_id: Optional[str] = None,
        start_playback: bool = True,
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
            devices_response = await self.client.get_available_devices(access_token)
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
                    (d for d in devices if d["name"].lower() == device_name_lower), None
                )

                # If no exact match, try partial match
                if not target_device:
                    target_device = next(
                        (d for d in devices if device_name_lower in d["name"].lower()),
                        None,
                    )

            if not target_device:
                available_names = [d["name"] for d in devices]
                raise NoActiveDeviceError(
                    f"Device '{device_name or device_id}' not found. "
                    f"Available devices: {', '.join(available_names)}"
                )

            # Transfer playback to target device
            await self.client.transfer_playback(
                access_token=access_token,
                device_id=target_device["id"],
                play=start_playback,
            )

            logger.info(f"Successfully switched to device: {target_device['name']}")

            return CommandResult(
                success=True,
                message=f"Switched playback to {target_device['name']}",
                data={
                    "device_id": target_device["id"],
                    "device_name": target_device["name"],
                    "device_type": target_device["type"],
                },
            )

        except NoActiveDeviceError:
            raise
        except Exception as e:
            logger.error(f"Failed to switch device: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to switch device: {str(e)}", e)


# Import client singleton (at module level to avoid circular import)
from app.services.spotify.client import spotify_client

# Create singleton instance
spotify_service = SpotifyService(client=spotify_client)
