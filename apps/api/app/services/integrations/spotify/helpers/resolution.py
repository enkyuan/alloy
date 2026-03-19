"""Candidate retrieval and resolution helpers for Spotify track requests."""

import asyncio
import logging
import re
from typing import Any, Optional

from app.core.config import settings
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
        preferred_uris: Optional[list[str]] = None,
        disable_clarifications: Optional[bool] = None,
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
        search_started = asyncio.get_running_loop().time()

        async def _search_variant(
            query_variant: str,
            variant_limit: int,
        ) -> list[dict[str, Any]]:
            try:
                search_results = await self.client.search(
                    access_token=access_token,
                    query=query_variant,
                    types="track",
                    limit=variant_limit,
                )
            except Exception as exc:
                logger.warning(
                    "Track search variant failed",
                    extra={"query": query_variant, "error": str(exc)},
                )
                return []

            tracks = search_results.get("tracks", {}).get("items", [])
            if not isinstance(tracks, list):
                return []

            hydrated: list[dict[str, Any]] = []
            for track in tracks:
                if isinstance(track, dict):
                    hydrated.append(
                        {
                            **track,
                            "_candidate_source": "catalog",
                            "_query_variant": query_variant,
                        }
                    )
            return hydrated

        search_tasks = [
            _search_variant(search_query, 30 if idx == 0 else 20)
            for idx, search_query in enumerate(search_queries)
        ]
        if search_tasks:
            variant_results = await asyncio.gather(*search_tasks)
            for candidates in variant_results:
                catalog_candidates.extend(candidates)

        search_elapsed_ms = int(
            (asyncio.get_running_loop().time() - search_started) * 1000
        )
        logger.info(
            "Completed Spotify variant search fanout",
            extra={
                "query": effective_query,
                "artist": artist,
                "variant_count": len(search_queries),
                "candidate_count": len(catalog_candidates),
                "elapsed_ms": search_elapsed_ms,
            },
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
        final_ranked = self._boost_ranked_tracks_with_uri_priors(
            final_ranked,
            preferred_uris,
            base_boost=self.TRACK_PRIOR_URI_BOOST_BASE,
            decay=self.TRACK_PRIOR_URI_BOOST_DECAY,
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
        no_clarify_mode = (
            settings.SPOTIFY_DISABLE_CLARIFICATION_MESSAGES
            if disable_clarifications is None
            else bool(disable_clarifications)
        )
        second_probability = (
            ranked_with_probs[1][2] if len(ranked_with_probs) > 1 else 0.0
        )
        second_track = ranked_with_probs[1][0] if len(ranked_with_probs) > 1 else None
        probability_margin = top_probability - second_probability
        second_score = final_ranked[1][1] if len(final_ranked) > 1 else 0.0
        score_margin = top_score - second_score
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

        def _canonical_track_title(normalized_track_name: str) -> str:
            return re.sub(
                r"\s*(?:\([^)]*\)|\[[^\]]*\]|[-–]\s*.*)$",
                "",
                normalized_track_name,
            ).strip()

        normalized_effective_query = self._normalize_match_text(effective_query)
        top_track_name = str(top_track.get("name", ""))
        top_track_name_norm = self._normalize_match_text(top_track_name)
        canonical_top_title = _canonical_track_title(top_track_name_norm)
        canonical_title_match = bool(
            normalized_effective_query
            and canonical_top_title == normalized_effective_query
        )
        canonical_title_match_count = 0
        for candidate_track, _, _ in ranked_with_probs[:5]:
            candidate_name_norm = self._normalize_match_text(
                str(candidate_track.get("name", ""))
            )
            candidate_canonical = _canonical_track_title(candidate_name_norm)
            if candidate_canonical == normalized_effective_query:
                canonical_title_match_count += 1
        title_similarity = self._similarity_score(
            normalized_effective_query, top_track_name_norm
        )
        title_overlap = self._token_overlap(
            normalized_effective_query, top_track_name_norm
        )
        normalized_requested_artist = self._normalize_match_text(artist or "")

        def _track_matches_requested_artist(candidate_track: dict[str, Any]) -> bool:
            if not normalized_requested_artist:
                return False
            candidate_artists = candidate_track.get("artists", [])
            candidate_artist_names = [
                str(item.get("name", ""))
                for item in candidate_artists
                if isinstance(item, dict) and item.get("name")
            ]
            candidate_artist_text = self._normalize_match_text(
                " ".join(candidate_artist_names)
            )
            if not candidate_artist_text:
                return False
            artist_similarity = self._similarity_score(
                normalized_requested_artist, candidate_artist_text
            )
            artist_overlap = self._token_overlap(
                normalized_requested_artist, candidate_artist_text
            )
            artist_phonetic = self._phonetic_similarity(
                normalized_requested_artist, candidate_artist_text
            )
            return (
                normalized_requested_artist == candidate_artist_text
                or normalized_requested_artist in candidate_artist_text
                or artist_overlap >= 0.65
                or artist_similarity >= 0.86
                or artist_phonetic >= 0.90
            )

        top_artist_match = _track_matches_requested_artist(top_track)
        matching_artist_count = sum(
            1
            for candidate_track, _, _ in ranked_with_probs[:5]
            if _track_matches_requested_artist(candidate_track)
        )
        top_popularity = max(0.0, float(top_track.get("popularity", 0.0)))
        second_popularity = (
            max(0.0, float(second_track.get("popularity", 0.0)))
            if isinstance(second_track, dict)
            else 0.0
        )
        popularity_margin = top_popularity - second_popularity
        top_variant_penalty = self._variant_penalty(effective_query, top_track)

        def _resolve_without_clarification() -> tuple[dict[str, Any], None]:
            constrained_min_score = self.TRACK_NO_CLARIFY_CONSTRAINED_MIN_SCORE
            constrained_min_margin = self.TRACK_NO_CLARIFY_CONSTRAINED_MARGIN_MIN
            default_min_score = self.TRACK_NO_CLARIFY_MIN_SCORE
            default_min_margin = self.TRACK_NO_CLARIFY_MARGIN_MIN

            min_score = constrained_min_score if constrained_request else default_min_score
            min_margin = (
                constrained_min_margin
                if constrained_request
                else default_min_margin
            )
            if top_score >= min_score and (
                score_margin >= min_margin or probability_margin >= min_margin
            ):
                logger.info(
                    "No-clarification mode selected top track by score+margin policy",
                    extra={
                        "query": effective_query,
                        "artist": artist,
                        "track_name": top_track_name,
                        "top_score": round(top_score, 4),
                        "score_margin": round(score_margin, 4),
                        "top_probability": round(top_probability, 4),
                        "probability_margin": round(probability_margin, 4),
                        "constrained_request": constrained_request,
                    },
                )
                return top_track, None

            if (
                top_score >= (min_score - 0.04)
                and top_popularity >= self.TRACK_NO_CLARIFY_POPULARITY_MIN
                and popularity_margin >= self.TRACK_NO_CLARIFY_POPULARITY_MARGIN_MIN
                and top_variant_penalty >= -0.05
            ):
                logger.info(
                    "No-clarification mode selected top track by popularity fallback",
                    extra={
                        "query": effective_query,
                        "artist": artist,
                        "track_name": top_track_name,
                        "top_score": round(top_score, 4),
                        "top_popularity": round(top_popularity, 2),
                        "second_popularity": round(second_popularity, 2),
                        "popularity_margin": round(popularity_margin, 2),
                    },
                )
                return top_track, None

            suggestions = [
                "Try including the artist name",
                "Try using the exact track title",
            ]
            raise SearchNoResultsError(effective_query, "track", suggestions)

        # Deterministic constrained pass:
        # when artist is specified, prefer exact canonical title + requested artist
        # matches across top candidates instead of clarifying.
        exact_constrained_candidates: list[tuple[dict[str, Any], float]] = []
        if normalized_requested_artist and normalized_effective_query:
            for candidate_track, candidate_score, _ in ranked_with_probs[:12]:
                candidate_name_norm = self._normalize_match_text(
                    str(candidate_track.get("name", ""))
                )
                candidate_canonical = _canonical_track_title(candidate_name_norm)
                if candidate_canonical != normalized_effective_query:
                    continue
                if not _track_matches_requested_artist(candidate_track):
                    continue
                exact_constrained_candidates.append((candidate_track, candidate_score))

        if exact_constrained_candidates:
            selected_track, selected_score = max(
                exact_constrained_candidates,
                key=lambda item: (
                    item[1],
                    float(item[0].get("popularity", 0.0)),
                ),
            )
            if selected_score >= (self.TRACK_CLARIFY_MIN - 0.12):
                logger.info(
                    "Track candidate selected by exact constrained title+artist pass",
                    extra={
                        "query": effective_query,
                        "artist": artist,
                        "selected_track_name": str(selected_track.get("name", "")),
                        "selected_score": round(selected_score, 4),
                        "candidate_count": len(exact_constrained_candidates),
                    },
                )
                return selected_track, None

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

        # Precision fallback for direct title requests:
        # if the top title canonically matches the query, do not fail just because
        # probability is diluted across many near-duplicate variants.
        if (
            not constrained_request
            and canonical_title_match
            and canonical_title_match_count == 1
            and top_score >= (self.TRACK_CONFIDENCE_MIN - 0.03)
            and score_margin >= (self.TRACK_CONFIDENCE_GAP / 2.0)
            and title_similarity >= 0.90
            and title_overlap >= 0.80
        ):
            logger.info(
                "Track candidate accepted by canonical exact-title fallback",
                extra={
                    "query": effective_query,
                    "track_name": top_track_name,
                    "top_score": round(top_score, 4),
                    "score_margin": round(score_margin, 4),
                    "top_probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "canonical_title_match_count": canonical_title_match_count,
                },
            )
            return top_track, None

        # Constrained exact fallback: if user provided artist and the top candidate
        # matches both title and artist strongly, prefer playing over clarification.
        if (
            normalized_requested_artist
            and canonical_title_match
            and top_artist_match
            and matching_artist_count >= 1
            and top_score >= (auto_score_min - 0.03)
            and (
                score_margin >= (self.TRACK_CONFIDENCE_GAP / 3.0)
                or probability_margin >= 0.03
            )
            and title_similarity >= 0.86
            and title_overlap >= 0.70
        ):
            logger.info(
                "Track candidate accepted by exact title+artist constrained fallback",
                extra={
                    "query": effective_query,
                    "artist": artist,
                    "track_name": top_track_name,
                    "top_score": round(top_score, 4),
                    "score_margin": round(score_margin, 4),
                    "top_probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "matching_artist_count": matching_artist_count,
                },
            )
            return top_track, None

        # Popularity tie-break fallback for constrained requests:
        # when exact title+artist still produces low probability due many close variants,
        # prefer the strongest non-variant canonical cut instead of clarifying.
        if (
            normalized_requested_artist
            and canonical_title_match
            and top_artist_match
            and top_variant_penalty >= -0.01
            and top_popularity >= 55.0
            and popularity_margin >= 5.0
            and top_score >= (auto_score_min - 0.08)
            and title_similarity >= 0.85
            and title_overlap >= 0.70
        ):
            logger.info(
                "Track candidate accepted by constrained popularity tie-break fallback",
                extra={
                    "query": effective_query,
                    "artist": artist,
                    "track_name": top_track_name,
                    "top_score": round(top_score, 4),
                    "top_probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "top_popularity": round(top_popularity, 2),
                    "second_popularity": round(second_popularity, 2),
                    "popularity_margin": round(popularity_margin, 2),
                },
            )
            return top_track, None

        # Low-churn constrained fallback:
        # prioritize execution for exact title+artist requests even when
        # probability mass is split across many nearby variants.
        if (
            normalized_requested_artist
            and canonical_title_match
            and top_artist_match
            and top_score >= (self.TRACK_CLARIFY_MIN - 0.02)
            and title_similarity >= 0.84
            and title_overlap >= 0.65
        ):
            logger.info(
                "Track candidate accepted by constrained low-churn fallback",
                extra={
                    "query": effective_query,
                    "artist": artist,
                    "track_name": top_track_name,
                    "top_score": round(top_score, 4),
                    "top_probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "top_popularity": round(top_popularity, 2),
                    "second_popularity": round(second_popularity, 2),
                },
            )
            return top_track, None

        # Direct-title dominant-hit fallback:
        # avoid repetitive clarification turns when one canonical title candidate
        # is clearly dominant by popularity and lexical fit.
        if (
            not constrained_request
            and canonical_title_match
            and top_score >= (self.TRACK_CLARIFY_MIN - 0.02)
            and title_similarity >= 0.85
            and title_overlap >= 0.70
            and top_variant_penalty >= -0.02
            and top_popularity >= 65.0
            and popularity_margin >= 8.0
        ):
            logger.info(
                "Track candidate accepted by direct-title dominant-hit fallback",
                extra={
                    "query": effective_query,
                    "track_name": top_track_name,
                    "top_score": round(top_score, 4),
                    "top_probability": round(top_probability, 4),
                    "probability_margin": round(probability_margin, 4),
                    "top_popularity": round(top_popularity, 2),
                    "second_popularity": round(second_popularity, 2),
                    "popularity_margin": round(popularity_margin, 2),
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
                        "artist": artist,
                        "top_track": top_track_name,
                        "top_score": round(top_score, 4),
                        "top_probability": round(top_probability, 4),
                        "probability_margin": round(probability_margin, 4),
                        "strong_candidates": len(strong_candidates),
                    },
                )
                if no_clarify_mode:
                    return _resolve_without_clarification()
                return None, self._build_clarification_result(
                    query=effective_query,
                    ranked_tracks=[
                        (track, score) for track, score, _ in ranked_with_probs
                    ],
                    artist=artist,
                    playlist_name=playlist_name,
                )
            if (
                top_score >= self.TRACK_CONFIDENCE_MIN
                and score_margin >= self.TRACK_CONFIDENCE_GAP
            ):
                logger.info(
                    "Low-probability distribution but strong top score margin; selecting top track",
                    extra={
                        "query": effective_query,
                        "track_name": top_track_name,
                        "top_score": round(top_score, 4),
                        "score_margin": round(score_margin, 4),
                        "top_probability": round(top_probability, 4),
                    },
                )
                return top_track, None

            logger.info(
                "Low-confidence single-candidate distribution; returning clarification",
                extra={
                    "query": effective_query,
                    "top_score": round(top_score, 4),
                    "top_probability": round(top_probability, 4),
                    "score_margin": round(score_margin, 4),
                },
            )
            if no_clarify_mode:
                return _resolve_without_clarification()
            return None, self._build_clarification_result(
                query=effective_query,
                ranked_tracks=[(track, score) for track, score, _ in ranked_with_probs],
                artist=artist,
                playlist_name=playlist_name,
            )

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
        if no_clarify_mode:
            return _resolve_without_clarification()
        return None, self._build_clarification_result(
            query=effective_query,
            ranked_tracks=[(track, score) for track, score, _ in ranked_with_probs],
            artist=artist,
            playlist_name=playlist_name,
        )
