"""Candidate retrieval and resolution helpers for Spotify track requests."""

import asyncio
import logging
import re
from typing import Any, Optional

from app.services.integrations.spotify.exceptions import SearchNoResultsError
from app.services.integrations.spotify.models import CommandResult

logger = logging.getLogger(__name__)


class SpotifyResolutionMixin:
    """Playlist collection and track candidate resolution workflows."""

    async def _collect_user_playlists(
        self: Any, access_token: str, max_playlists: int = 200
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

    async def _verify_playback_context_uri(
        self: Any, access_token: str, expected_context_uri: str
    ) -> Optional[bool]:
        """Best-effort verification for playlist/album playback context.

        Spotify may take a short moment to reflect context changes, so this method
        performs a few lightweight polls before returning unknown (`None`).
        """
        if not expected_context_uri:
            return None

        observed_context = False
        for attempt in range(3):
            try:
                await asyncio.sleep(0.35)
                playback = await self.client.get_current_playback(access_token)
                context = playback.get("context", {})
                context_uri = ""
                if isinstance(context, dict):
                    context_uri = str(context.get("uri", ""))
                if context_uri:
                    observed_context = True
                    if context_uri == expected_context_uri:
                        return True
                    logger.debug(
                        "Playback context verification attempt mismatch",
                        extra={
                            "expected_context_uri": expected_context_uri,
                            "current_context_uri": context_uri,
                            "attempt": attempt + 1,
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "Playback context verification failed",
                    extra={
                        "expected_context_uri": expected_context_uri,
                        "attempt": attempt + 1,
                        "error": str(exc),
                    },
                )
                return None

        return False if observed_context else None

    async def _resolve_track_candidate(
        self: Any,
        query: str,
        access_token: str,
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[CommandResult]]:
        """Resolve the best track candidate or return a clarification result."""
        raw_query = query.strip()
        lowered_query = raw_query.lower()
        prefer_non_remix = any(
            token in lowered_query
            for token in ["not the remix", "not remix", "no remix"]
        )
        cleaned_query = re.sub(
            r"\bnot\s+(?:the\s+)?remix\b", "", raw_query, flags=re.IGNORECASE
        )
        cleaned_query = re.sub(
            r"\bno\s+remix\b", "", cleaned_query, flags=re.IGNORECASE
        )
        cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()
        effective_query = cleaned_query or raw_query

        ranked_candidates: list[tuple[dict[str, Any], float]] = []

        # If user asks for a track from a playlist, resolve likely playlist candidates first.
        if playlist_name:
            logger.info(
                "Searching for track in requested playlist first",
                extra={"playlist_name": playlist_name, "query": effective_query},
            )
            user_playlists = await self._collect_user_playlists(access_token)
            playlist_ranked = self._rank_playlist_candidates(
                playlists=user_playlists,
                query=playlist_name,
                source="user_library",
            )
            playlist_ranked = self._rerank_playlist_candidates(
                playlist_ranked,
                query=playlist_name,
                top_k=8,
            )
            playlist_probs = self._ranked_with_probabilities(playlist_ranked)

            selected_playlists: list[tuple[dict[str, Any], float]] = []
            if playlist_probs:
                top_playlist, _, top_prob = playlist_probs[0]
                second_prob = playlist_probs[1][2] if len(playlist_probs) > 1 else 0.0
                margin = top_prob - second_prob
                if top_prob >= self.PLAYLIST_CLARIFY_MIN:
                    selected_playlists.append((top_playlist, 0.14))
                    if (
                        margin < self.PLAYLIST_AUTO_MARGIN_MIN
                        and len(playlist_probs) > 1
                    ):
                        selected_playlists.append((playlist_probs[1][0], 0.08))

                logger.info(
                    "Playlist constraint resolution complete",
                    extra={
                        "playlist_name": playlist_name,
                        "top_probability": round(top_prob, 4),
                        "margin": round(margin, 4),
                        "selected_playlist_count": len(selected_playlists),
                    },
                )

            if selected_playlists:
                for selected_playlist, boost in selected_playlists:
                    playlist_id = str(selected_playlist.get("id", ""))
                    if not playlist_id:
                        continue
                    playlist_tracks_rows = await self.client.get_playlist_tracks(
                        access_token=access_token,
                        playlist_id=playlist_id,
                        max_items=250,
                    )
                    playlist_tracks: list[dict[str, Any]] = []
                    for row in playlist_tracks_rows:
                        if not isinstance(row, dict):
                            continue
                        track = row.get("track")
                        if isinstance(track, dict):
                            playlist_tracks.append(
                                {**track, "_candidate_source": "user_playlist"}
                            )

                    ranked_from_playlist = self._rank_track_candidates(
                        playlist_tracks,
                        query=effective_query,
                        artist=artist,
                        prefer_non_remix=prefer_non_remix,
                        playlist_boost=boost,
                    )
                    ranked_candidates.extend(ranked_from_playlist)
                    logger.info(
                        "Ranked candidates from playlist constraint",
                        extra={
                            "playlist_name": selected_playlist.get("name"),
                            "playlist_tracks": len(playlist_tracks),
                            "ranked_candidates": len(ranked_from_playlist),
                            "playlist_boost": boost,
                        },
                    )
            else:
                logger.warning(
                    "Requested playlist was not confidently matched in user library",
                    extra={"playlist_name": playlist_name},
                )

        # Global candidate union retrieval with multiple lexical query variants.
        search_queries = self._build_track_search_queries(effective_query, artist)
        logger.info(
            "Searching Spotify catalog with query variants",
            extra={"query_variants": search_queries, "artist": artist},
        )
        catalog_candidates: list[dict[str, Any]] = []
        for idx, search_query in enumerate(search_queries):
            try:
                search_results = await self.client.search(
                    access_token=access_token,
                    query=search_query,
                    types="track",
                    limit=30 if idx == 0 else 20,
                )
            except Exception as exc:
                logger.warning(
                    "Track search variant failed",
                    extra={"query": search_query, "error": str(exc)},
                )
                continue

            tracks = search_results.get("tracks", {}).get("items", [])
            if not isinstance(tracks, list):
                continue
            for track in tracks:
                if isinstance(track, dict):
                    catalog_candidates.append(
                        {
                            **track,
                            "_candidate_source": "catalog",
                            "_query_variant": search_query,
                        }
                    )

        if catalog_candidates:
            ranked_candidates.extend(
                self._rank_track_candidates(
                    tracks=catalog_candidates,
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
        final_ranked = self._rerank_track_candidates(
            final_ranked,
            query=effective_query,
            artist=artist,
            top_k=20,
        )
        ranked_with_probs = self._ranked_with_probabilities(final_ranked)

        logger.info(
            "Resolved ranked track candidates",
            extra={
                "query": effective_query,
                "artist": artist,
                "playlist_name": playlist_name,
                "candidate_count": len(final_ranked),
                "top_score": round(final_ranked[0][1], 4) if final_ranked else None,
                "top_probability": round(ranked_with_probs[0][2], 4)
                if ranked_with_probs
                else None,
            },
        )

        if not ranked_with_probs:
            raise SearchNoResultsError(effective_query, "track")

        top_track, top_score, top_probability = ranked_with_probs[0]
        second_probability = (
            ranked_with_probs[1][2] if len(ranked_with_probs) > 1 else 0.0
        )
        probability_margin = top_probability - second_probability
        constrained_request = bool(artist or playlist_name)
        auto_prob_min = (
            self.TRACK_CONSTRAINED_PROB_MIN
            if constrained_request
            else self.TRACK_AUTO_PROB_MIN
        )
        auto_margin_min = (
            self.TRACK_CONSTRAINED_MARGIN_MIN
            if constrained_request
            else self.TRACK_AUTO_MARGIN_MIN
        )
        auto_score_min = (
            self.TRACK_CONFIDENCE_MIN - 0.05
            if constrained_request
            else self.TRACK_CONFIDENCE_MIN
        )

        if (
            top_probability >= auto_prob_min
            and probability_margin >= auto_margin_min
            and top_score >= auto_score_min
        ):
            logger.info(
                "Track candidate passed auto-play threshold policy",
                extra={
                    "track_name": top_track.get("name"),
                    "score": round(top_score, 4),
                    "probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "constrained_request": constrained_request,
                    "auto_score_min": round(auto_score_min, 4),
                },
            )
            return top_track, None

        if top_score < (self.TRACK_CLARIFY_MIN - 0.15):
            suggestions = [
                "Try including the artist name",
                "Try using the exact track title",
                "Try adding album or playlist context",
            ]
            raise SearchNoResultsError(effective_query, "track", suggestions)

        if top_probability < self.TRACK_CLARIFY_MIN:
            strong_candidates = [
                prob for _, _, prob in ranked_with_probs[:3] if prob >= 0.20
            ]
            if len(strong_candidates) >= 2:
                logger.info(
                    "Low-confidence track result has multiple strong alternatives; clarifying",
                    extra={
                        "query": effective_query,
                        "top_probability": round(top_probability, 4),
                        "strong_candidates": len(strong_candidates),
                    },
                )
                return None, self._build_clarification_result(
                    query=effective_query,
                    ranked_tracks=[
                        (track, score) for track, score, _ in ranked_with_probs
                    ],
                    artist=artist,
                    playlist_name=playlist_name,
                )
            suggestions = [
                "Try including the artist name",
                "Try using the exact track title",
                "Try adding album or playlist context",
            ]
            raise SearchNoResultsError(effective_query, "track", suggestions)

        logger.info(
            "Track candidate requires clarification by threshold policy",
            extra={
                "query": effective_query,
                "top_score": round(top_score, 4),
                "top_probability": round(top_probability, 4),
                "probability_margin": round(probability_margin, 4),
                "auto_probability_min": auto_prob_min,
                "auto_margin_min": auto_margin_min,
            },
        )
        return None, self._build_clarification_result(
            query=effective_query,
            ranked_tracks=[(track, score) for track, score, _ in ranked_with_probs],
            artist=artist,
            playlist_name=playlist_name,
        )
