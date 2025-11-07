"""Uber Controller for voice command execution."""
import asyncio
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Optional, TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from app.services.uber import UberService

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class UberControllerError(Exception):
    """Base exception for UberController errors."""
    
    def __init__(self, message: str, error_code: str = "UBER_ERROR", suggestions: Optional[list[str]] = None):
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


class NoLocationError(UberControllerError):
    """Raised when location information is missing."""
    
    def __init__(
        self,
        message: str = "Location information is required for ride booking.",
        suggestions: Optional[list[str]] = None
    ):
        """Initialize with message and optional suggestions.
        
        Args:
            message: User-friendly error message
            suggestions: Optional list of suggestions for the user
        """
        default_suggestions = [
            "Try specifying a destination address",
            "Make sure location services are enabled",
            "Try saying 'book a ride to [specific address]'"
        ]
        
        super().__init__(message, "NO_LOCATION", suggestions or default_suggestions)


class RideBookingError(UberControllerError):
    """Raised when ride booking fails."""
    
    def __init__(
        self,
        message: str = "Failed to book ride",
        reason: Optional[str] = None,
        suggestions: Optional[list[str]] = None
    ):
        """Initialize with message, reason, and optional suggestions.
        
        Args:
            message: User-friendly error message
            reason: Optional reason for booking failure
            suggestions: Optional list of suggestions for the user
        """
        default_suggestions = [
            "Try booking through the Uber app directly",
            "Check if Uber is available in your area",
            "Make sure your payment method is valid"
        ]
        
        if reason == "no_drivers":
            message = "No drivers available in your area"
            default_suggestions = [
                "Try again in a few minutes",
                "Consider using a different ride type",
                "Check if there are any local events affecting availability"
            ]
        elif reason == "invalid_location":
            message = "The specified location is not valid"
            default_suggestions = [
                "Try using a more specific address",
                "Make sure the location exists",
                "Try using landmarks or well-known places"
            ]
        
        super().__init__(message, "BOOKING_ERROR", suggestions or default_suggestions)


class AuthenticationError(UberControllerError):
    """Raised when authentication fails."""
    
    def __init__(
        self,
        message: str = "Failed to authenticate with Uber",
        reason: Optional[str] = None
    ):
        """Initialize with message and optional reason.
        
        Args:
            message: User-friendly error message
            reason: Optional reason for authentication failure
        """
        suggestions = [
            "Try reconnecting Uber in settings",
            "Make sure you're logged into Uber",
            "Check that you've granted the necessary permissions"
        ]
        
        if reason == "token_expired":
            message = "Your Uber session has expired"
            suggestions = [
                "Please reconnect Uber in settings",
                "This usually happens after being logged out"
            ]
        elif reason == "no_integration":
            message = "Uber is not connected"
            suggestions = [
                "Connect Uber in the app settings",
                "Make sure you complete the Uber authorization"
            ]
        
        super().__init__(message, "AUTH_ERROR", suggestions)
        self.reason = reason


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    message: str
    data: dict
    error: Optional[str] = None


# ============================================================================
# Uber Controller
# ============================================================================


class UberController:
    """Controller for executing Uber commands from voice agent."""

    def __init__(self, uber_service: "UberService"):
        """Initialize UberController.

        Args:
            uber_service: UberService instance for API calls
        """
        self.uber = uber_service

    async def book_ride_to_destination(
        self,
        destination: str,
        access_token: str,
        pickup_location: Optional[str] = None
    ) -> CommandResult:
        """Book a ride to a destination using deep linking.

        Args:
            destination: Destination address or name
            access_token: Valid Uber access token
            pickup_location: Optional pickup location (uses current location if not provided)

        Returns:
            CommandResult with deep link information

        Raises:
            NoLocationError: If destination is not provided
            AuthenticationError: If authentication fails
            RideBookingError: If booking fails
        """
        try:
            if not destination or destination.strip() == "":
                raise NoLocationError("Please specify where you'd like to go")

            logger.info(f"Booking ride to: {destination}")

            # Generate deep link for ride booking
            # Note: For voice commands, we use deep linking rather than API booking
            # to provide a better user experience and avoid complex location handling
            deep_link = self.uber.generate_deep_link(
                pickup_address=pickup_location,
                destination_address=destination
            )

            # Also generate web link as fallback
            web_link = self.uber.generate_web_link(
                pickup_address=pickup_location,
                destination_address=destination
            )

            return CommandResult(
                success=True,
                message=f"Opening Uber to book a ride to {destination}",
                data={
                    "destination": destination,
                    "pickup_location": pickup_location,
                    "deep_link": deep_link,
                    "web_link": web_link,
                    "action": "open_uber_app"
                }
            )

        except NoLocationError:
            raise
        except Exception as e:
            logger.error(f"Failed to book ride: {str(e)}", exc_info=True)
            raise RideBookingError(f"Failed to book ride: {str(e)}")

    async def book_ride_from_to(
        self,
        pickup: str,
        destination: str,
        access_token: str
    ) -> CommandResult:
        """Book a ride from pickup to destination.

        Args:
            pickup: Pickup address or name
            destination: Destination address or name
            access_token: Valid Uber access token

        Returns:
            CommandResult with deep link information

        Raises:
            NoLocationError: If pickup or destination is not provided
            RideBookingError: If booking fails
        """
        try:
            if not pickup or pickup.strip() == "":
                raise NoLocationError("Please specify the pickup location")
            
            if not destination or destination.strip() == "":
                raise NoLocationError("Please specify the destination")

            logger.info(f"Booking ride from {pickup} to {destination}")

            # Generate deep link
            deep_link = self.uber.generate_deep_link(
                pickup_address=pickup,
                destination_address=destination
            )

            web_link = self.uber.generate_web_link(
                pickup_address=pickup,
                destination_address=destination
            )

            return CommandResult(
                success=True,
                message=f"Opening Uber to book a ride from {pickup} to {destination}",
                data={
                    "pickup_location": pickup,
                    "destination": destination,
                    "deep_link": deep_link,
                    "web_link": web_link,
                    "action": "open_uber_app"
                }
            )

        except NoLocationError:
            raise
        except Exception as e:
            logger.error(f"Failed to book ride: {str(e)}", exc_info=True)
            raise RideBookingError(f"Failed to book ride: {str(e)}")

    async def get_ride_history(self, access_token: str, limit: int = 5) -> CommandResult:
        """Get user's ride history.

        Args:
            access_token: Valid Uber access token
            limit: Number of rides to return

        Returns:
            CommandResult with ride history

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            logger.info("Getting ride history")

            # Get ride history
            history = await self.uber.get_ride_history(access_token, limit)

            if not history:
                return CommandResult(
                    success=True,
                    message="You have no recent rides",
                    data={"rides": []}
                )

            # Format ride history for voice response
            recent_rides = []
            for ride in history[:3]:  # Limit to 3 most recent for voice
                ride_info = {
                    "destination": ride.get("end_city", {}).get("display_name", "Unknown destination"),
                    "date": ride.get("start_time", "Unknown date"),
                    "status": ride.get("status", "Unknown status")
                }
                recent_rides.append(ride_info)

            message = f"You have {len(history)} recent rides. "
            if recent_rides:
                last_ride = recent_rides[0]
                message += f"Your last ride was to {last_ride['destination']}"

            return CommandResult(
                success=True,
                message=message,
                data={
                    "rides": recent_rides,
                    "total_rides": len(history)
                }
            )

        except Exception as e:
            logger.error(f"Failed to get ride history: {str(e)}", exc_info=True)
            raise AuthenticationError(f"Failed to get ride history: {str(e)}")

    async def get_profile(self, access_token: str) -> CommandResult:
        """Get user's Uber profile.

        Args:
            access_token: Valid Uber access token

        Returns:
            CommandResult with profile information

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            logger.info("Getting Uber profile")

            profile = await self.uber.get_user_profile(access_token)

            return CommandResult(
                success=True,
                message=f"Your Uber account: {profile.get('first_name', 'Unknown')} {profile.get('last_name', '')}",
                data={
                    "first_name": profile.get("first_name"),
                    "last_name": profile.get("last_name"),
                    "email": profile.get("email"),
                    "mobile": profile.get("mobile")
                }
            )

        except Exception as e:
            logger.error(f"Failed to get profile: {str(e)}", exc_info=True)
            raise AuthenticationError(f"Failed to get profile: {str(e)}")

    def generate_ride_deep_link(
        self,
        destination: Optional[str] = None,
        pickup: Optional[str] = None
    ) -> CommandResult:
        """Generate deep link for ride booking (no API call needed).

        Args:
            destination: Destination address
            pickup: Optional pickup address

        Returns:
            CommandResult with deep link

        Raises:
            NoLocationError: If no destination provided
        """
        try:
            if not destination:
                raise NoLocationError("Please specify a destination")

            deep_link = self.uber.generate_deep_link(
                pickup_address=pickup,
                destination_address=destination
            )

            web_link = self.uber.generate_web_link(
                pickup_address=pickup,
                destination_address=destination
            )

            pickup_text = f" from {pickup}" if pickup else ""
            
            return CommandResult(
                success=True,
                message=f"Opening Uber to book a ride{pickup_text} to {destination}",
                data={
                    "deep_link": deep_link,
                    "web_link": web_link,
                    "destination": destination,
                    "pickup": pickup,
                    "action": "open_uber_app"
                }
            )

        except NoLocationError:
            raise
        except Exception as e:
            logger.error(f"Failed to generate deep link: {str(e)}", exc_info=True)
            raise RideBookingError(f"Failed to generate ride link: {str(e)}")


# Import uber_service singleton
from app.services.uber import uber_service

# Create singleton instance
uber_controller = UberController(uber_service=uber_service)