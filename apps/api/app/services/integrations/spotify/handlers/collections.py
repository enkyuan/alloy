"""Playlist and album command handlers for Spotify service."""

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


class SpotifyCollectionCommandsMixin:
    """Search/play command handlers for playlists and albums."""

    @retry_on_transient_error(max_retries=2, delay=1.0)
    async def search_and_play_playlist(
        self: Any, query: str, access_token: str, user_playlists_only: bool = False
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
            query_text = query.strip()
            logger.info(
                "Searching for playlist",
                extra={"query": query_text, "user_playlists_only": user_playlists_only},
            )

            ranked_candidates: list[tuple[dict[str, Any], float]] = []

            user_playlists = await self._collect_user_playlists(access_token)
            if user_playlists:
                user_ranked = self._rank_playlist_candidates(
                    playlists=user_playlists,
                    query=query_text,
                    source="user_library",
                )
                ranked_candidates.extend(
                    [
                        ({**playlist, "_candidate_source": "user_library"}, score)
                        for playlist, score in user_ranked
                    ]
                )

            if not user_playlists_only:
                search_results = await self.client.search(
                    access_token=access_token,
                    query=query_text,
                    types="playlist",
                    limit=15,
                )
                catalog_items = search_results.get("playlists", {}).get("items", [])
                catalog_playlists = [
                    item for item in catalog_items if isinstance(item, dict)
                ]
                if catalog_playlists:
                    catalog_ranked = self._rank_playlist_candidates(
                        playlists=catalog_playlists,
                        query=query_text,
                        source="catalog",
                    )
                    ranked_candidates.extend(
                        [
                            ({**playlist, "_candidate_source": "catalog"}, score)
                            for playlist, score in catalog_ranked
                        ]
                    )

            # Deduplicate by playlist id/uri and keep highest score per candidate.
            deduped: dict[str, tuple[dict[str, Any], float]] = {}
            for playlist, score in ranked_candidates:
                key = str(
                    playlist.get("id")
                    or playlist.get("uri")
                    or playlist.get("name", "")
                )
                if not key:
                    continue
                existing = deduped.get(key)
                if existing is None or score > existing[1]:
                    deduped[key] = (playlist, score)
            final_ranked = sorted(
                deduped.values(), key=lambda item: item[1], reverse=True
            )
            final_ranked = self._rerank_playlist_candidates(
                final_ranked,
                query=query_text,
                top_k=20,
            )
            ranked_with_probs = self._ranked_with_probabilities(final_ranked)

            if not ranked_with_probs:
                suggestions = [
                    "Check the spelling of the playlist name",
                    "Try searching for a different playlist",
                ]
                if user_playlists_only:
                    suggestions.append("Make sure the playlist exists in your library")
                else:
                    suggestions.append(
                        "Try saying 'play my playlist ...' to prefer your library"
                    )
                raise SearchNoResultsError(query_text, "playlist", suggestions)

            top_playlist, top_score, top_probability = ranked_with_probs[0]
            second_probability = (
                ranked_with_probs[1][2] if len(ranked_with_probs) > 1 else 0.0
            )
            probability_margin = top_probability - second_probability

            if (
                top_probability < self.PLAYLIST_AUTO_PROB_MIN
                or probability_margin < self.PLAYLIST_AUTO_MARGIN_MIN
                or top_score < self.PLAYLIST_CONFIDENCE_MIN
            ):
                logger.info(
                    "Playlist selection requires clarification",
                    extra={
                        "query": query_text,
                        "top_score": round(top_score, 4),
                        "top_probability": round(top_probability, 4),
                        "probability_margin": round(probability_margin, 4),
                        "candidate_count": len(final_ranked),
                    },
                )

                if top_score < (self.PLAYLIST_CLARIFY_MIN - 0.12):
                    suggestions = [
                        "Try using the exact playlist title",
                        "Say 'play my playlist ...' to prefer your library",
                        "Try including the playlist owner name",
                    ]
                    raise SearchNoResultsError(query_text, "playlist", suggestions)

                if top_probability < self.PLAYLIST_CLARIFY_MIN:
                    strong_candidates = [
                        prob for _, _, prob in ranked_with_probs[:3] if prob >= 0.20
                    ]
                    if len(strong_candidates) >= 2:
                        logger.info(
                            "Low-confidence playlist result has multiple strong alternatives; clarifying",
                            extra={
                                "query": query_text,
                                "top_probability": round(top_probability, 4),
                                "strong_candidates": len(strong_candidates),
                            },
                        )
                        return self._build_playlist_clarification_result(
                            query=query_text, ranked_playlists=final_ranked
                        )
                    suggestions = [
                        "Try using the exact playlist title",
                        "Say 'play my playlist ...' to prefer your library",
                        "Try including the playlist owner name",
                    ]
                    raise SearchNoResultsError(query_text, "playlist", suggestions)

                return self._build_playlist_clarification_result(
                    query=query_text, ranked_playlists=final_ranked
                )

            selected_playlist = top_playlist
            selected_score = top_score
            playlist_name = str(selected_playlist["name"])
            playlist_uri = str(selected_playlist["uri"])
            playlist_id = str(selected_playlist["id"])
            playlist_source = str(selected_playlist.get("_candidate_source", "catalog"))

            logger.info(
                "Selected playlist candidate",
                extra={
                    "playlist_name": playlist_name,
                    "playlist_id": playlist_id,
                    "source": playlist_source,
                    "score": round(selected_score, 4),
                },
            )

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

            verified = await self._verify_playback_context_uri(
                access_token=access_token,
                expected_context_uri=playlist_uri,
            )
            if verified is False:
                logger.warning(
                    "Playlist playback command acknowledged but context verification mismatch",
                    extra={
                        "playlist_id": playlist_id,
                        "playlist_name": playlist_name,
                        "source": playlist_source,
                    },
                )

            return CommandResult(
                success=True,
                message=f"Now playing playlist '{playlist_name}'",
                data={
                    "playlist_name": playlist_name,
                    "uri": playlist_uri,
                    "playlist_id": playlist_id,
                    "owner": selected_playlist.get("owner", {}).get("display_name", ""),
                    "tracks_total": selected_playlist.get("tracks", {}).get("total", 0),
                    "source": playlist_source,
                    "score": round(selected_score, 4),
                    "probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "verified": verified,
                },
            )

        except (NoActiveDeviceError, SearchNoResultsError, PremiumRequiredError):
            raise
        except Exception as e:
            logger.error("Failed to search and play playlist: %s", e, exc_info=True)

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
        self: Any, query: str, access_token: str, artist: Optional[str] = None
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

            logger.info("Searching for album: %s", search_query)

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

            logger.info("Selected album: %s by %s", album_name, album_artist)

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
            logger.error("Failed to search and play album: %s", e, exc_info=True)

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
