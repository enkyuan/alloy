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
    PLAYLIST_AUTO_PROB_MIN = 0.88
    PLAYLIST_AUTO_MARGIN_MIN = 0.12
    PLAYLIST_CLARIFY_MIN = 0.60


spotify_service = SpotifyService(client=spotify_client)

__all__ = ["SpotifyService", "spotify_service", "SpotifyClient", "spotify_client"]
