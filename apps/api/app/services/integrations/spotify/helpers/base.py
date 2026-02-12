"""Core Spotify service mixin methods."""

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy.orm import Session

from app.models.integration import Integration
from app.services.integrations.spotify.client import spotify_client
from app.services.integrations.spotify.exceptions import SpotifyAPIError

if TYPE_CHECKING:
    from app.services.integrations.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)


class SpotifyServiceBaseMixin:
    """Core initialization and error/device helpers for Spotify service."""

    def __init__(self: Any, client: Optional["SpotifyClient"] = None) -> None:
        """Initialize SpotifyService.

        Args:
            client: SpotifyClient instance for API calls (defaults to singleton)
        """
        self.client = client or spotify_client

    async def get_valid_token(self: Any, integration: Integration, db: Session) -> str:
        """Get a valid Spotify access token using the client helper."""
        return await self.client.get_valid_token(integration, db)

    def _check_premium_error(self: Any, error: Exception) -> bool:
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

    def _extract_status_code(self: Any, error: Exception) -> Optional[int]:
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

    async def get_active_device(self: Any, access_token: str) -> Optional[str]:
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
