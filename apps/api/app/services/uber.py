"""Uber API service for ride booking and management."""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


class UberService:
    """Service for Uber API operations."""

    BASE_URL = "https://api.uber.com/v1.2"
    SANDBOX_URL = "https://sandbox-api.uber.com/v1.2"

    def __init__(self, use_sandbox: bool = True):
        """Initialize Uber service.
        
        Args:
            use_sandbox: Whether to use sandbox environment for testing
        """
        self.base_url = self.SANDBOX_URL if use_sandbox else self.BASE_URL

    async def refresh_token(self, integration: Integration, db: Session) -> str:
        """Refresh Uber access token.

        Args:
            integration: Integration model with refresh token
            db: Database session

        Returns:
            New access token

        Raises:
            Exception: If token refresh fails
        """
        try:
            if not integration.refresh_token:
                raise Exception("No refresh token available")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://login.uber.com/oauth/v2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": integration.refresh_token,
                        "client_id": settings.UBER_CLIENT_ID,
                        "client_secret": settings.UBER_CLIENT_SECRET
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )

                if response.status_code != 200:
                    logger.error(f"Uber token refresh failed: {response.text}")
                    raise Exception(f"Failed to refresh token: {response.text}")

                token_data = response.json()

                # Update integration
                integration.access_token = token_data["access_token"]
                integration.expires_at = datetime.utcnow() + timedelta(
                    seconds=token_data.get("expires_in", 3600)
                )
                integration.updated_at = datetime.utcnow()

                if "refresh_token" in token_data:
                    integration.refresh_token = token_data["refresh_token"]

                db.commit()

                logger.info(f"Successfully refreshed Uber token for user {integration.user_id}")
                return integration.access_token

        except Exception as e:
            logger.error(f"Failed to refresh Uber token: {str(e)}", exc_info=True)
            raise

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
        """Get valid access token, refreshing if needed.

        Args:
            integration: Integration model
            db: Database session

        Returns:
            Valid access token

        Raises:
            Exception: If token refresh fails
        """
        # Check if token is expired or expires soon (within 5 minutes)
        if integration.expires_at and \
           integration.expires_at < datetime.utcnow() + timedelta(minutes=5):
            logger.info("Uber token expired or expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return integration.access_token

    async def get_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Get user's Uber profile.

        Args:
            access_token: Valid Uber access token

        Returns:
            User profile data

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()

    async def get_products(self, access_token: str, latitude: float, longitude: float) -> List[Dict[str, Any]]:
        """Get available Uber products at a location.

        Args:
            access_token: Valid Uber access token
            latitude: Pickup latitude
            longitude: Pickup longitude

        Returns:
            List of available products

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/products",
                params={
                    "latitude": latitude,
                    "longitude": longitude
                },
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json().get("products", [])

    async def get_price_estimates(
        self,
        access_token: str,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float
    ) -> List[Dict[str, Any]]:
        """Get price estimates for a trip.

        Args:
            access_token: Valid Uber access token
            start_latitude: Pickup latitude
            start_longitude: Pickup longitude
            end_latitude: Destination latitude
            end_longitude: Destination longitude

        Returns:
            List of price estimates

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/estimates/price",
                params={
                    "start_latitude": start_latitude,
                    "start_longitude": start_longitude,
                    "end_latitude": end_latitude,
                    "end_longitude": end_longitude
                },
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json().get("prices", [])

    async def get_time_estimates(
        self,
        access_token: str,
        start_latitude: float,
        start_longitude: float,
        product_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get time estimates for pickup.

        Args:
            access_token: Valid Uber access token
            start_latitude: Pickup latitude
            start_longitude: Pickup longitude
            product_id: Optional specific product ID

        Returns:
            List of time estimates

        Raises:
            httpx.HTTPError: If API request fails
        """
        params = {
            "start_latitude": start_latitude,
            "start_longitude": start_longitude
        }
        if product_id:
            params["product_id"] = product_id

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/estimates/time",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json().get("times", [])

    async def request_ride(
        self,
        access_token: str,
        product_id: str,
        start_latitude: float,
        start_longitude: float,
        end_latitude: float,
        end_longitude: float,
        start_address: Optional[str] = None,
        end_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Request a ride.

        Args:
            access_token: Valid Uber access token
            product_id: Product ID for the ride type
            start_latitude: Pickup latitude
            start_longitude: Pickup longitude
            end_latitude: Destination latitude
            end_longitude: Destination longitude
            start_address: Optional pickup address
            end_address: Optional destination address

        Returns:
            Ride request details

        Raises:
            httpx.HTTPError: If API request fails
        """
        ride_data = {
            "product_id": product_id,
            "start_latitude": start_latitude,
            "start_longitude": start_longitude,
            "end_latitude": end_latitude,
            "end_longitude": end_longitude
        }

        if start_address:
            ride_data["start_address"] = start_address
        if end_address:
            ride_data["end_address"] = end_address

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/requests",
                json=ride_data,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            return response.json()

    async def get_ride_details(self, access_token: str, request_id: str) -> Dict[str, Any]:
        """Get details of a specific ride request.

        Args:
            access_token: Valid Uber access token
            request_id: Ride request ID

        Returns:
            Ride details

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/requests/{request_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()

    async def cancel_ride(self, access_token: str, request_id: str) -> Dict[str, Any]:
        """Cancel a ride request.

        Args:
            access_token: Valid Uber access token
            request_id: Ride request ID

        Returns:
            Cancellation response

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/requests/{request_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json() if response.content else {}

    async def get_ride_history(self, access_token: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get user's ride history.

        Args:
            access_token: Valid Uber access token
            limit: Number of rides to return

        Returns:
            List of past rides

        Raises:
            httpx.HTTPError: If API request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/history",
                params={"limit": limit},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json().get("history", [])

    def generate_deep_link(
        self,
        pickup_latitude: Optional[float] = None,
        pickup_longitude: Optional[float] = None,
        pickup_address: Optional[str] = None,
        destination_latitude: Optional[float] = None,
        destination_longitude: Optional[float] = None,
        destination_address: Optional[str] = None,
        product_id: Optional[str] = None
    ) -> str:
        """Generate Uber deep link for ride booking.

        Args:
            pickup_latitude: Pickup latitude
            pickup_longitude: Pickup longitude
            pickup_address: Pickup address
            destination_latitude: Destination latitude
            destination_longitude: Destination longitude
            destination_address: Destination address
            product_id: Specific product ID

        Returns:
            Uber deep link URL
        """
        params = {}

        # Pickup location
        if pickup_latitude and pickup_longitude:
            params["pickup[latitude]"] = pickup_latitude
            params["pickup[longitude]"] = pickup_longitude
        elif pickup_address:
            params["pickup[formatted_address]"] = pickup_address

        # Destination
        if destination_latitude and destination_longitude:
            params["dropoff[latitude]"] = destination_latitude
            params["dropoff[longitude]"] = destination_longitude
        elif destination_address:
            params["dropoff[formatted_address]"] = destination_address

        # Product type
        if product_id:
            params["product_id"] = product_id

        # Build deep link
        if params:
            query_string = urlencode(params)
            return f"uber://ride?{query_string}"
        else:
            return "uber://ride"

    def generate_web_link(
        self,
        pickup_latitude: Optional[float] = None,
        pickup_longitude: Optional[float] = None,
        pickup_address: Optional[str] = None,
        destination_latitude: Optional[float] = None,
        destination_longitude: Optional[float] = None,
        destination_address: Optional[str] = None
    ) -> str:
        """Generate Uber web link for ride booking.

        Args:
            pickup_latitude: Pickup latitude
            pickup_longitude: Pickup longitude
            pickup_address: Pickup address
            destination_latitude: Destination latitude
            destination_longitude: Destination longitude
            destination_address: Destination address

        Returns:
            Uber web link URL
        """
        params = {}

        # Pickup location
        if pickup_latitude and pickup_longitude:
            params["pickup[latitude]"] = pickup_latitude
            params["pickup[longitude]"] = pickup_longitude
        elif pickup_address:
            params["pickup[formatted_address]"] = pickup_address

        # Destination
        if destination_latitude and destination_longitude:
            params["dropoff[latitude]"] = destination_latitude
            params["dropoff[longitude]"] = destination_longitude
        elif destination_address:
            params["dropoff[formatted_address]"] = destination_address

        # Build web link
        if params:
            query_string = urlencode(params)
            return f"https://m.uber.com/ul/?{query_string}"
        else:
            return "https://m.uber.com/ul/"


# Create singleton instance
uber_service = UberService(use_sandbox=True)  # Use sandbox for development