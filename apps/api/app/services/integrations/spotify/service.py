"""Spotify service facade composed from focused mixins."""

from app.services.integrations.spotify.client import SpotifyClient, spotify_client
from app.services.integrations.spotify.handlers import (
    SpotifyCollectionCommandsMixin,
    SpotifyTrackCommandsMixin,
    SpotifyTransportCommandsMixin,
)
from app.services.integrations.spotify.helpers import (
    SpotifyPlaybackMixin,
    SpotifyRankingMixin,
    SpotifyResolutionMixin,
    SpotifyServiceBaseMixin,
)


class SpotifyService(
    SpotifyServiceBaseMixin,
    SpotifyRankingMixin,
    SpotifyResolutionMixin,
    SpotifyPlaybackMixin,
    SpotifyTrackCommandsMixin,
    SpotifyCollectionCommandsMixin,
    SpotifyTransportCommandsMixin,
):
    """High-level service for executing Spotify commands from voice agent."""

    TRACK_CONFIDENCE_MIN = 0.62
    TRACK_CONFIDENCE_GAP = 0.08
    PLAYLIST_CONFIDENCE_MIN = 0.60
    PLAYLIST_CONFIDENCE_GAP = 0.06
    TRACK_AUTO_PROB_MIN = 0.90
    TRACK_AUTO_MARGIN_MIN = 0.15
    TRACK_CONSTRAINED_PROB_MIN = 0.84
    TRACK_CONSTRAINED_MARGIN_MIN = 0.10
    TRACK_CLARIFY_MIN = 0.65
    TRACK_PRIOR_URI_BOOST_BASE = 0.09
    TRACK_PRIOR_URI_BOOST_DECAY = 0.02
    TRACK_NO_CLARIFY_MIN_SCORE = 0.60
    TRACK_NO_CLARIFY_MARGIN_MIN = 0.02
    TRACK_NO_CLARIFY_CONSTRAINED_MIN_SCORE = 0.56
    TRACK_NO_CLARIFY_CONSTRAINED_MARGIN_MIN = 0.015
    TRACK_NO_CLARIFY_POPULARITY_MIN = 70.0
    TRACK_NO_CLARIFY_POPULARITY_MARGIN_MIN = 8.0
    PLAYLIST_AUTO_PROB_MIN = 0.88
    PLAYLIST_AUTO_MARGIN_MIN = 0.12
    PLAYLIST_CLARIFY_MIN = 0.60
    PLAYLIST_NO_CLARIFY_MIN_SCORE = 0.62
    PLAYLIST_NO_CLARIFY_MARGIN_MIN = 0.02


spotify_service = SpotifyService(client=spotify_client)

__all__ = ["SpotifyService", "spotify_service", "SpotifyClient", "spotify_client"]
