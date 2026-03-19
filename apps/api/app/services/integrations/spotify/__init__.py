"""Spotify service package for API integration and command orchestration."""

# Export client (low-level API operations)
from app.services.integrations.spotify.client import SpotifyClient, spotify_client

# Export service (high-level command orchestration)
from app.services.integrations.spotify.service import SpotifyService, spotify_service

# Export exceptions
from app.services.integrations.spotify.exceptions import (
    SpotifyError,
    NoActiveDeviceError,
    SearchNoResultsError,
    SpotifyAPIError,
    PremiumRequiredError,
    AuthenticationError,
)

# Export models
from app.services.integrations.spotify.models import CommandResult

__all__ = [
    # Clients
    "SpotifyClient",
    "spotify_client",
    # Services
    "SpotifyService",
    "spotify_service",
    # Exceptions
    "SpotifyError",
    "NoActiveDeviceError",
    "SearchNoResultsError",
    "SpotifyAPIError",
    "PremiumRequiredError",
    "AuthenticationError",
    # Models
    "CommandResult",
]
