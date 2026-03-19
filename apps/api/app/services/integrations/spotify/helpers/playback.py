"""Playback metadata and verification helpers for Spotify commands."""

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SpotifyPlaybackMixin:
    """Track payload shaping and queue-first playback verification helpers."""

    def _track_payload(self: Any, track: dict[str, Any]) -> dict[str, Any]:
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
        self: Any, access_token: str, expected_track_id: str
    ) -> Optional[bool]:
        """Best-effort verification for playback state after play/skip commands."""
        if not expected_track_id:
            return None
        observed_track = False
        for attempt in range(3):
            try:
                await asyncio.sleep(0.35)
                playback = await self.client.get_current_playback(access_token)
                current_track_id = str(playback.get("item", {}).get("id", ""))
                if not current_track_id:
                    continue
                observed_track = True
                if current_track_id == expected_track_id:
                    return True
                logger.debug(
                    "Playback verification attempt mismatch",
                    extra={
                        "expected_track_id": expected_track_id,
                        "current_track_id": current_track_id,
                        "attempt": attempt + 1,
                    },
                )
                continue
            except Exception as exc:
                logger.warning(
                    "Playback verification failed",
                    extra={
                        "expected_track_id": expected_track_id,
                        "attempt": attempt + 1,
                        "error": str(exc),
                    },
                )
                return None
        return False if observed_track else None

    async def _verify_track_changed(
        self: Any, access_token: str, previous_track_id: str
    ) -> Optional[bool]:
        """Best-effort check that current playback is not the previous track."""
        if not previous_track_id:
            return None
        observed_track = False
        for attempt in range(3):
            try:
                await asyncio.sleep(0.35)
                playback = await self.client.get_current_playback(access_token)
                current_track_id = str(playback.get("item", {}).get("id", ""))
                if not current_track_id:
                    continue
                observed_track = True
                if current_track_id != previous_track_id:
                    return True
                logger.debug(
                    "Track-change verification attempt still on previous track",
                    extra={
                        "previous_track_id": previous_track_id,
                        "attempt": attempt + 1,
                    },
                )
                continue
            except Exception as exc:
                logger.warning(
                    "Track-change verification failed",
                    extra={
                        "previous_track_id": previous_track_id,
                        "attempt": attempt + 1,
                        "error": str(exc),
                    },
                )
                return None
        return False if observed_track else None

    async def _play_track_queue_first(
        self: Any,
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
                await self.client.skip_next(
                    access_token=access_token, device_id=device_id
                )
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
            await self.client.play(
                access_token=access_token, uri=track_uri, device_id=device_id
            )
            direct_play_used = True

        verified = await self._verify_playback_track(access_token, track_id)
        stalled_recovery_used = False

        if verified is False and not direct_play_used:
            logger.warning(
                "Queue-first verification mismatch; attempting direct-play recovery",
                extra={"track_name": track_name, "track_id": track_id},
            )
            await self.client.play(
                access_token=access_token, uri=track_uri, device_id=device_id
            )
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
