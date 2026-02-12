"""Ranking and clarification helpers for Spotify entities."""

import logging
import math
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from app.services.integrations.spotify.models import CommandResult

logger = logging.getLogger(__name__)


class SpotifyRankingMixin:
    """Text normalization, candidate ranking, and clarification builders."""

    def _normalize_match_text(self: Any, value: str) -> str:
        """Normalize text for similarity and token overlap checks."""
        normalized = value.lower().strip()
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _similarity_score(self: Any, left: str, right: str) -> float:
        """Return a fuzzy similarity score in [0, 1]."""
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _token_overlap(self: Any, left: str, right: str) -> float:
        """Return token overlap score in [0, 1]."""
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _phrase_overlap(self: Any, left: str, right: str, n: int = 2) -> float:
        """Return n-gram phrase overlap score in [0, 1]."""
        left_tokens = left.split()
        right_tokens = right.split()
        if len(left_tokens) < n or len(right_tokens) < n:
            return 0.0
        left_ngrams = {
            " ".join(left_tokens[i : i + n]) for i in range(len(left_tokens) - n + 1)
        }
        right_ngrams = {
            " ".join(right_tokens[i : i + n]) for i in range(len(right_tokens) - n + 1)
        }
        if not left_ngrams or not right_ngrams:
            return 0.0
        return len(left_ngrams & right_ngrams) / len(left_ngrams | right_ngrams)

    def _soundex_token(self: Any, token: str) -> str:
        """Return a lightweight Soundex code for phonetic matching."""
        normalized = re.sub(r"[^a-z0-9]", "", token.lower())
        if not normalized:
            return ""
        first_char = normalized[0]
        mappings = {
            "b": "1",
            "f": "1",
            "p": "1",
            "v": "1",
            "c": "2",
            "g": "2",
            "j": "2",
            "k": "2",
            "q": "2",
            "s": "2",
            "x": "2",
            "z": "2",
            "d": "3",
            "t": "3",
            "l": "4",
            "m": "5",
            "n": "5",
            "r": "6",
        }
        digits: list[str] = []
        previous = mappings.get(first_char, "")
        for char in normalized[1:]:
            digit = mappings.get(char, "")
            if not digit:
                previous = ""
                continue
            if digit != previous:
                digits.append(digit)
            previous = digit
        return (first_char.upper() + "".join(digits) + "000")[:4]

    def _phonetic_text(self: Any, value: str) -> str:
        """Encode text as whitespace-separated Soundex tokens."""
        tokens = self._normalize_match_text(value).split()
        encoded = [self._soundex_token(token) for token in tokens]
        return " ".join(code for code in encoded if code)

    def _phonetic_similarity(self: Any, left: str, right: str) -> float:
        """Return phonetic similarity score in [0, 1]."""
        left_code = self._phonetic_text(left)
        right_code = self._phonetic_text(right)
        if not left_code or not right_code:
            return 0.0
        return max(
            self._similarity_score(left_code, right_code),
            self._token_overlap(left_code, right_code),
        )

    def _char_ngram_counts(self: Any, value: str, n: int = 3) -> dict[str, float]:
        """Return sparse character n-gram counts for embedding-style similarity."""
        normalized = self._normalize_match_text(value)
        compact = normalized.replace(" ", "")
        if not compact:
            return {}
        if len(compact) <= n:
            return {compact: 1.0}
        counts: dict[str, float] = {}
        for i in range(len(compact) - n + 1):
            gram = compact[i : i + n]
            counts[gram] = counts.get(gram, 0.0) + 1.0
        return counts

    def _cosine_similarity_sparse(
        self: Any, left: dict[str, float], right: dict[str, float]
    ) -> float:
        """Compute cosine similarity for sparse vectors in [0, 1]."""
        if not left or not right:
            return 0.0
        dot = 0.0
        for key, value in left.items():
            dot += value * right.get(key, 0.0)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        cosine = dot / (left_norm * right_norm)
        return max(0.0, min(cosine, 1.0))

    def _semantic_similarity(self: Any, left: str, right: str) -> float:
        """Return embedding-style semantic similarity using char n-gram vectors."""
        left_vec = self._char_ngram_counts(left)
        right_vec = self._char_ngram_counts(right)
        return self._cosine_similarity_sparse(left_vec, right_vec)

    def _ranked_with_probabilities(
        self: Any,
        ranked_items: list[tuple[dict[str, Any], float]],
        temperature: float = 6.0,
    ) -> list[tuple[dict[str, Any], float, float]]:
        """Attach calibrated probabilities to ranked scores using softmax."""
        if not ranked_items:
            return []
        clipped_temp = max(0.5, min(temperature, 10.0))
        max_score = max(score for _, score in ranked_items)
        exp_scores = [
            math.exp((score - max_score) * clipped_temp) for _, score in ranked_items
        ]
        total = sum(exp_scores)
        if total <= 0:
            uniform_prob = 1.0 / len(ranked_items)
            return [(item, score, uniform_prob) for item, score in ranked_items]
        with_probs: list[tuple[dict[str, Any], float, float]] = []
        for (item, score), exp_score in zip(ranked_items, exp_scores):
            with_probs.append((item, score, exp_score / total))
        return with_probs

    def _build_track_search_queries(
        self: Any, query: str, artist: Optional[str]
    ) -> list[str]:
        """Build lexical query variants for union candidate generation."""
        normalized_query = self._normalize_match_text(query)
        queries: list[str] = []
        if artist:
            queries.append(f"track:{query} artist:{artist}")
        queries.append(query)
        if normalized_query and normalized_query != query.lower():
            queries.append(normalized_query)

        tokens = [token for token in normalized_query.split() if len(token) > 2]
        if len(tokens) >= 3:
            queries.append(" ".join(tokens[:3]))
        elif len(tokens) >= 2:
            queries.append(" ".join(tokens[:2]))

        # Keep order stable while deduplicating and limit request fan-out.
        deduped: list[str] = []
        for candidate in queries:
            compact = candidate.strip()
            if not compact:
                continue
            if compact not in deduped:
                deduped.append(compact)
            if len(deduped) >= 4:
                break
        return deduped

    def _is_remix_track(self: Any, track: dict[str, Any]) -> bool:
        """Check whether a track appears to be a remix cut."""
        name = str(track.get("name", "")).lower()
        album = str(track.get("album", {}).get("name", "")).lower()
        return "remix" in name or "remix" in album

    def _query_requests_variant(self: Any, query: str, variant: str) -> bool:
        """Return whether the user explicitly requested a variant marker."""
        normalized = self._normalize_match_text(query)
        return variant in normalized

    def _variant_penalty(self: Any, query: str, track: dict[str, Any]) -> float:
        """Apply penalties for undesired track variants unless requested."""
        markers = ("remix", "live", "karaoke", "instrumental")
        track_name = str(track.get("name", "")).lower()
        album_name = str(track.get("album", {}).get("name", "")).lower()
        penalty = 0.0
        for marker in markers:
            if marker not in track_name and marker not in album_name:
                continue
            if self._query_requests_variant(query, marker):
                continue
            if marker == "karaoke":
                penalty -= 0.24
            elif marker == "instrumental":
                penalty -= 0.16
            else:
                penalty -= 0.10
        return penalty

    def _rank_track_candidates(
        self: Any,
        tracks: list[dict[str, Any]],
        query: str,
        artist: Optional[str] = None,
        prefer_non_remix: bool = False,
        playlist_boost: float = 0.0,
    ) -> list[tuple[dict[str, Any], float]]:
        """Rank track candidates using a hybrid multi-feature score."""
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
            phrase_overlap = self._phrase_overlap(
                normalized_query, track_name_norm, n=2
            )
            contains_bonus = (
                1.0 if normalized_query and normalized_query in track_name_norm else 0.0
            )
            exact_title_bonus = 1.0 if normalized_query == track_name_norm else 0.0
            title_phonetic = self._phonetic_similarity(
                normalized_query, track_name_norm
            )

            track_context = f"{track_name_norm} {artists_norm}".strip()
            semantic_similarity = self._semantic_similarity(
                normalized_query, track_context
            )

            artist_similarity = 0.0
            artist_phonetic = 0.0
            artist_exact_bonus = 0.0
            if normalized_artist:
                artist_similarity = self._similarity_score(
                    normalized_artist, artists_norm
                )
                artist_phonetic = self._phonetic_similarity(
                    normalized_artist, artists_norm
                )
                if normalized_artist and normalized_artist == artists_norm:
                    artist_exact_bonus = 0.25
                elif normalized_artist and normalized_artist in artists_norm:
                    artist_exact_bonus = 0.12

            popularity = max(0.0, min(float(track.get("popularity", 0)) / 100.0, 1.0))
            source = str(track.get("_candidate_source", "catalog"))
            source_boost = 0.10 if source == "user_playlist" else 0.0
            variant_penalty = self._variant_penalty(query, track)

            score = (
                (title_similarity * 0.28)
                + (title_overlap * 0.14)
                + (phrase_overlap * 0.16)
                + (title_phonetic * 0.10)
                + (semantic_similarity * 0.16)
                + (contains_bonus * 0.05)
                + (exact_title_bonus * 0.07)
                + (popularity * 0.04)
                + source_boost
                + variant_penalty
            )

            if normalized_artist:
                score += artist_similarity * 0.14
                score += artist_phonetic * 0.08
                score += artist_exact_bonus

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
                    "phrase_overlap": round(phrase_overlap, 4),
                    "title_phonetic": round(title_phonetic, 4),
                    "semantic_similarity": round(semantic_similarity, 4),
                    "artist_similarity": round(artist_similarity, 4),
                    "artist_phonetic": round(artist_phonetic, 4),
                    "artist_exact_bonus": round(artist_exact_bonus, 4),
                    "popularity": round(popularity, 4),
                    "source_boost": round(source_boost, 4),
                    "variant_penalty": round(variant_penalty, 4),
                    "playlist_boost": round(playlist_boost, 4),
                },
            )

        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    def _format_track_option(self: Any, track: dict[str, Any]) -> str:
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
        self: Any, ranked_tracks: list[tuple[dict[str, Any], float]]
    ) -> bool:
        """Return True when top candidates are too close to auto-select safely."""
        ranked_with_probs = self._ranked_with_probabilities(ranked_tracks)
        if not ranked_with_probs:
            return True
        top_probability = ranked_with_probs[0][2]
        second_probability = (
            ranked_with_probs[1][2] if len(ranked_with_probs) > 1 else 0.0
        )
        probability_margin = top_probability - second_probability
        return (
            top_probability < self.TRACK_AUTO_PROB_MIN
            or probability_margin < self.TRACK_AUTO_MARGIN_MIN
        )

    def _build_clarification_result(
        self: Any,
        query: str,
        ranked_tracks: list[tuple[dict[str, Any], float]],
        artist: Optional[str] = None,
        playlist_name: Optional[str] = None,
    ) -> CommandResult:
        """Create a clarification response when match confidence is low."""
        options = [self._format_track_option(track) for track, _ in ranked_tracks[:3]]
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

    def _rank_playlist_candidates(
        self: Any,
        playlists: list[dict[str, Any]],
        query: str,
        *,
        source: str,
    ) -> list[tuple[dict[str, Any], float]]:
        """Rank playlist candidates by hybrid lexical/phonetic/semantic relevance.

        Args:
            playlists: Playlist rows from Spotify.
            query: User's requested playlist name.
            source: Candidate source ("user_library" or "catalog") for score boosting.

        Returns:
            Ranked `(playlist, score)` pairs with highest score first.
        """
        normalized_query = self._normalize_match_text(query)
        ranked: list[tuple[dict[str, Any], float]] = []

        for playlist in playlists:
            playlist_name = str(playlist.get("name", "")).strip()
            if not playlist_name:
                continue

            playlist_name_norm = self._normalize_match_text(playlist_name)
            title_similarity = self._similarity_score(
                normalized_query, playlist_name_norm
            )
            title_overlap = self._token_overlap(normalized_query, playlist_name_norm)
            phrase_overlap = self._phrase_overlap(
                normalized_query, playlist_name_norm, n=2
            )
            phonetic_similarity = self._phonetic_similarity(
                normalized_query, playlist_name_norm
            )
            semantic_similarity = self._semantic_similarity(
                normalized_query, playlist_name_norm
            )
            contains_bonus = (
                1.0
                if normalized_query and normalized_query in playlist_name_norm
                else 0.0
            )
            exact_title_bonus = 1.0 if normalized_query == playlist_name_norm else 0.0

            owner_data = playlist.get("owner", {})
            owner_display = ""
            if isinstance(owner_data, dict):
                owner_display = str(owner_data.get("display_name", "")).strip()
            owner_bonus = 0.0 if owner_display else -0.02

            source_boost = 0.12 if source == "user_library" else 0.0
            score = (
                (title_similarity * 0.26)
                + (title_overlap * 0.13)
                + (phrase_overlap * 0.16)
                + (phonetic_similarity * 0.12)
                + (semantic_similarity * 0.18)
                + (contains_bonus * 0.08)
                + (exact_title_bonus * 0.07)
                + owner_bonus
                + source_boost
            )
            score = max(0.0, min(score, 1.5))
            ranked.append((playlist, score))

            logger.debug(
                "Playlist candidate ranked",
                extra={
                    "playlist_name": playlist_name,
                    "source": source,
                    "score": round(score, 4),
                    "title_similarity": round(title_similarity, 4),
                    "title_overlap": round(title_overlap, 4),
                    "phrase_overlap": round(phrase_overlap, 4),
                    "phonetic_similarity": round(phonetic_similarity, 4),
                    "semantic_similarity": round(semantic_similarity, 4),
                    "contains_bonus": round(contains_bonus, 4),
                    "exact_title_bonus": round(exact_title_bonus, 4),
                },
            )

        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    def _format_playlist_option(self: Any, playlist: dict[str, Any]) -> str:
        """Format a human-readable playlist option label."""
        name = str(playlist.get("name", "Unknown playlist"))
        owner = playlist.get("owner", {})
        owner_name = ""
        if isinstance(owner, dict):
            owner_name = str(owner.get("display_name", "")).strip()
        return f"{name} by {owner_name}" if owner_name else name

    def _is_ambiguous_playlist_match(
        self: Any, ranked_playlists: list[tuple[dict[str, Any], float]]
    ) -> bool:
        """Return True when top playlist matches are too close for safe auto-play."""
        ranked_with_probs = self._ranked_with_probabilities(ranked_playlists)
        if not ranked_with_probs:
            return True
        top_probability = ranked_with_probs[0][2]
        second_probability = (
            ranked_with_probs[1][2] if len(ranked_with_probs) > 1 else 0.0
        )
        probability_margin = top_probability - second_probability
        return (
            top_probability < self.PLAYLIST_AUTO_PROB_MIN
            or probability_margin < self.PLAYLIST_AUTO_MARGIN_MIN
        )

    def _build_playlist_clarification_result(
        self: Any,
        query: str,
        ranked_playlists: list[tuple[dict[str, Any], float]],
    ) -> CommandResult:
        """Create a clarification response for ambiguous playlist selection."""
        options = [
            self._format_playlist_option(playlist)
            for playlist, _ in ranked_playlists[:3]
        ]
        options_text = ", ".join(options) if options else "No close matches available."
        message = (
            f"I found multiple playlists for '{query}'. Did you mean: {options_text}?"
        )
        return CommandResult(
            success=True,
            message=message,
            data={
                "requires_clarification": True,
                "query": query,
                "options": options,
            },
        )

    def _cross_encoder_track_score(
        self: Any,
        query: str,
        track: dict[str, Any],
        artist: Optional[str],
    ) -> float:
        """Context-aware rerank score for a single track candidate."""
        track_name = str(track.get("name", ""))
        artist_names = [
            str(item.get("name", ""))
            for item in track.get("artists", [])
            if isinstance(item, dict) and item.get("name")
        ]
        album_name = ""
        album_data = track.get("album", {})
        if isinstance(album_data, dict):
            album_name = str(album_data.get("name", ""))
        query_context = f"{query} {artist or ''}".strip()
        candidate_context = (
            f"{track_name} {' '.join(artist_names)} {album_name}".strip()
        )
        semantic = self._semantic_similarity(query_context, candidate_context)
        lexical = self._similarity_score(
            self._normalize_match_text(query_context),
            self._normalize_match_text(candidate_context),
        )
        phonetic = self._phonetic_similarity(query_context, candidate_context)
        return max(
            0.0, min((semantic * 0.55) + (lexical * 0.30) + (phonetic * 0.15), 1.0)
        )

    def _rerank_track_candidates(
        self: Any,
        ranked_tracks: list[tuple[dict[str, Any], float]],
        *,
        query: str,
        artist: Optional[str],
        top_k: int = 20,
    ) -> list[tuple[dict[str, Any], float]]:
        """Apply second-stage reranking to the highest-scoring tracks."""
        if not ranked_tracks:
            return []

        head = ranked_tracks[:top_k]
        tail = ranked_tracks[top_k:]
        reranked_head: list[tuple[dict[str, Any], float]] = []
        for track, coarse_score in head:
            deep_score = self._cross_encoder_track_score(query, track, artist)
            final_score = (coarse_score * 0.58) + (deep_score * 0.42)
            reranked_head.append((track, max(0.0, min(final_score, 1.5))))
        reranked_head.sort(key=lambda item: item[1], reverse=True)
        return reranked_head + tail

    def _cross_encoder_playlist_score(
        self: Any, query: str, playlist: dict[str, Any]
    ) -> float:
        """Context-aware rerank score for a playlist candidate."""
        playlist_name = str(playlist.get("name", ""))
        owner_data = playlist.get("owner", {})
        owner_name = ""
        if isinstance(owner_data, dict):
            owner_name = str(owner_data.get("display_name", ""))
        query_context = query
        candidate_context = f"{playlist_name} {owner_name}".strip()
        semantic = self._semantic_similarity(query_context, candidate_context)
        lexical = self._similarity_score(
            self._normalize_match_text(query_context),
            self._normalize_match_text(candidate_context),
        )
        phonetic = self._phonetic_similarity(query_context, candidate_context)
        return max(
            0.0, min((semantic * 0.50) + (lexical * 0.32) + (phonetic * 0.18), 1.0)
        )

    def _rerank_playlist_candidates(
        self: Any,
        ranked_playlists: list[tuple[dict[str, Any], float]],
        *,
        query: str,
        top_k: int = 20,
    ) -> list[tuple[dict[str, Any], float]]:
        """Apply second-stage reranking to the highest-scoring playlists."""
        if not ranked_playlists:
            return []

        head = ranked_playlists[:top_k]
        tail = ranked_playlists[top_k:]
        reranked_head: list[tuple[dict[str, Any], float]] = []
        for playlist, coarse_score in head:
            deep_score = self._cross_encoder_playlist_score(query, playlist)
            final_score = (coarse_score * 0.56) + (deep_score * 0.44)
            reranked_head.append((playlist, max(0.0, min(final_score, 1.5))))
        reranked_head.sort(key=lambda item: item[1], reverse=True)
        return reranked_head + tail
