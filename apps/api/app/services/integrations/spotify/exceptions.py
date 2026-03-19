"""Spotify service exceptions."""

from typing import Optional


class SpotifyError(Exception):
    """Base exception for Spotify service errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "SPOTIFY_ERROR",
        suggestions: Optional[list[str]] = None,
    ):
        """Initialize error with message, code, and optional suggestions.

        Args:
            message: User-friendly error message
            error_code: Machine-readable error code
            suggestions: Optional list of suggestions for the user
        """
        self.message = message
        self.error_code = error_code
        self.suggestions = suggestions or []
        super().__init__(self.message)


class NoActiveDeviceError(SpotifyError):
    """Raised when no active Spotify device is found."""

    def __init__(
        self,
        message: str = "No active Spotify device found. Please open Spotify on a device.",
        available_devices: Optional[list[str]] = None,
    ):
        """Initialize with message and optional list of available devices.

        Args:
            message: User-friendly error message
            available_devices: Optional list of available device names
        """
        suggestions = []
        if available_devices:
            suggestions = [
                f"Try opening Spotify on: {', '.join(available_devices)}",
                "Make sure Spotify is running on at least one device",
            ]
        else:
            suggestions = [
                "Open Spotify on your phone, computer, or speaker",
                "Make sure the device is connected to the internet",
                "Try refreshing your Spotify app",
            ]

        super().__init__(message, "NO_DEVICE", suggestions)
        self.available_devices = available_devices or []


class SearchNoResultsError(SpotifyError):
    """Raised when search returns no results."""

    def __init__(
        self,
        query: str,
        search_type: str = "track",
        suggestions: Optional[list[str]] = None,
    ):
        """Initialize with query, search type, and optional suggestions.

        Args:
            query: The search query that returned no results
            search_type: Type of content searched (track, album, playlist, artist)
            suggestions: Optional list of alternative suggestions
        """
        message = f"Couldn't find {search_type} '{query}'"

        # Generate helpful suggestions
        default_suggestions = [
            "Try being more specific with the name",
            "Check the spelling",
            f"Try including the artist name for {search_type}s",
        ]

        if search_type == "playlist":
            default_suggestions = [
                "Try searching for a different playlist",
                "Make sure the playlist name is spelled correctly",
                "Try creating the playlist first in Spotify",
            ]

        super().__init__(message, "NO_RESULTS", suggestions or default_suggestions)
        self.query = query
        self.search_type = search_type


class SpotifyAPIError(SpotifyError):
    """Raised when Spotify API call fails."""

    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        is_retryable: bool = False,
        status_code: Optional[int] = None,
    ):
        """Initialize with message, original error, and retry information.

        Args:
            message: User-friendly error message
            original_error: The original exception that caused this error
            is_retryable: Whether the operation can be retried
            status_code: HTTP status code if applicable
        """
        suggestions = []

        # Provide context-specific suggestions based on status code
        if status_code == 429:
            suggestions = [
                "Spotify is rate limiting requests",
                "Please wait a moment and try again",
            ]
            is_retryable = True
        elif status_code == 503:
            suggestions = [
                "Spotify service is temporarily unavailable",
                "Please try again in a few moments",
            ]
            is_retryable = True
        elif status_code in [500, 502, 504]:
            suggestions = [
                "Spotify is experiencing technical difficulties",
                "Please try again later",
            ]
            is_retryable = True
        elif is_retryable:
            suggestions = ["Please try your command again"]
        else:
            suggestions = [
                "Check your internet connection",
                "Try reconnecting Spotify in settings",
            ]

        super().__init__(message, "API_ERROR", suggestions)
        self.original_error = original_error
        self.is_retryable = is_retryable
        self.status_code = status_code


class PremiumRequiredError(SpotifyError):
    """Raised when operation requires Spotify Premium."""

    def __init__(
        self,
        message: str = "This feature requires Spotify Premium",
        feature: Optional[str] = None,
    ):
        """Initialize with message and optional feature name.

        Args:
            message: User-friendly error message
            feature: The specific feature that requires premium
        """
        suggestions = [
            "Upgrade to Spotify Premium to use this feature",
            "Try using the Spotify app directly for free tier features",
        ]

        if feature:
            message = f"{feature} requires Spotify Premium"

        super().__init__(message, "PREMIUM_REQUIRED", suggestions)
        self.feature = feature


class AuthenticationError(SpotifyError):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Failed to authenticate with Spotify",
        reason: Optional[str] = None,
    ):
        """Initialize with message and optional reason.

        Args:
            message: User-friendly error message
            reason: Optional reason for authentication failure
        """
        suggestions = [
            "Try reconnecting Spotify in settings",
            "Make sure you're logged into Spotify",
            "Check that you've granted the necessary permissions",
        ]

        if reason == "token_expired":
            message = "Your Spotify session has expired"
            suggestions = [
                "Please reconnect Spotify in settings",
                "This usually happens after being logged out",
            ]
        elif reason == "no_integration":
            message = "Spotify is not connected"
            suggestions = [
                "Connect Spotify in the app settings",
                "Make sure you complete the Spotify authorization",
            ]
        elif reason == "refresh_failed":
            message = "Failed to refresh your Spotify session"
            suggestions = [
                "Please reconnect Spotify in settings",
                "You may need to log out and log back in",
            ]

        super().__init__(message, "AUTH_ERROR", suggestions)
        self.reason = reason
