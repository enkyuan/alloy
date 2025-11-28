"""Calendly API service."""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


class CalendlyService:
    """Service for Calendly API operations."""

    BASE_URL = "https://api.calendly.com"

    async def refresh_token(self, integration: Integration, db: Session) -> str:
        """Refresh Calendly access token.

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
                    "https://auth.calendly.com/oauth/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": integration.refresh_token,
                        "client_id": settings.CALENDLY_CLIENT_ID,
                        "client_secret": settings.CALENDLY_CLIENT_SECRET
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )

                if response.status_code != 200:
                    logger.error(f"Calendly token refresh failed: {response.text}")
                    raise Exception(f"Failed to refresh token: {response.text}")

                token_data = response.json()

                # Update integration
                integration.access_token = token_data["access_token"]
                integration.expires_at = datetime.utcnow() + timedelta(
                    seconds=token_data.get("expires_in", 7200)
                )
                integration.updated_at = datetime.utcnow()

                if "refresh_token" in token_data:
                    integration.refresh_token = token_data["refresh_token"]

                db.commit()

                logger.info(f"Successfully refreshed Calendly token for user {integration.user_id}")
                return integration.access_token

        except Exception as e:
            logger.error(f"Failed to refresh Calendly token: {str(e)}", exc_info=True)
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
            logger.info("Calendly token expired or expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return integration.access_token

    # ============================================================================
    # User
    # ============================================================================

    async def get_current_user(self, access_token: str) -> Dict[str, Any]:
        """Get current user information.

        Args:
            access_token: Valid Calendly access token

        Returns:
            User information

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/users/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get user: {response.text}")

            return response.json().get("resource", {})

    # ============================================================================
    # Event Types
    # ============================================================================

    async def get_event_types(
        self,
        access_token: str,
        user_uri: str,
        active: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Get user's event types.

        Args:
            access_token: Valid Calendly access token
            user_uri: User URI
            active: Filter by active status

        Returns:
            List of event types

        Raises:
            Exception: If API call fails
        """
        params = {"user": user_uri}
        if active is not None:
            params["active"] = str(active).lower()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/event_types",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get event types: {response.text}")

            return response.json().get("collection", [])

    async def get_event_type(self, access_token: str, event_type_uuid: str) -> Dict[str, Any]:
        """Get a specific event type.

        Args:
            access_token: Valid Calendly access token
            event_type_uuid: Event type UUID

        Returns:
            Event type details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/event_types/{event_type_uuid}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get event type: {response.text}")

            return response.json().get("resource", {})

    # ============================================================================
    # Scheduled Events
    # ============================================================================

    async def get_scheduled_events(
        self,
        access_token: str,
        user_uri: Optional[str] = None,
        organization_uri: Optional[str] = None,
        status: Optional[str] = None,
        min_start_time: Optional[str] = None,
        max_start_time: Optional[str] = None,
        count: int = 20
    ) -> List[Dict[str, Any]]:
        """Get scheduled events.

        Args:
            access_token: Valid Calendly access token
            user_uri: Filter by user URI
            organization_uri: Filter by organization URI
            status: Filter by status (active, canceled)
            min_start_time: Minimum start time (ISO 8601)
            max_start_time: Maximum start time (ISO 8601)
            count: Number of results

        Returns:
            List of scheduled events

        Raises:
            Exception: If API call fails
        """
        params = {"count": count}
        if user_uri:
            params["user"] = user_uri
        if organization_uri:
            params["organization"] = organization_uri
        if status:
            params["status"] = status
        if min_start_time:
            params["min_start_time"] = min_start_time
        if max_start_time:
            params["max_start_time"] = max_start_time

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/scheduled_events",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get scheduled events: {response.text}")

            return response.json().get("collection", [])

    async def get_scheduled_event(
        self,
        access_token: str,
        event_uuid: str
    ) -> Dict[str, Any]:
        """Get a specific scheduled event.

        Args:
            access_token: Valid Calendly access token
            event_uuid: Event UUID

        Returns:
            Scheduled event details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/scheduled_events/{event_uuid}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get scheduled event: {response.text}")

            return response.json().get("resource", {})

    async def cancel_scheduled_event(
        self,
        access_token: str,
        event_uuid: str,
        reason: Optional[str] = None
    ) -> None:
        """Cancel a scheduled event.

        Args:
            access_token: Valid Calendly access token
            event_uuid: Event UUID
            reason: Cancellation reason

        Raises:
            Exception: If API call fails
        """
        data = {}
        if reason:
            data["reason"] = reason

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/scheduled_events/{event_uuid}/cancellation",
                json=data if data else None,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to cancel event: {response.text}")

    # ============================================================================
    # Event Invitees
    # ============================================================================

    async def get_event_invitees(
        self,
        access_token: str,
        event_uuid: str,
        status: Optional[str] = None,
        count: int = 100
    ) -> List[Dict[str, Any]]:
        """Get invitees for a scheduled event.

        Args:
            access_token: Valid Calendly access token
            event_uuid: Event UUID
            status: Filter by status (active, canceled)
            count: Number of results

        Returns:
            List of invitees

        Raises:
            Exception: If API call fails
        """
        params = {"count": count}
        if status:
            params["status"] = status

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/scheduled_events/{event_uuid}/invitees",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get invitees: {response.text}")

            return response.json().get("collection", [])

    async def get_invitee(
        self,
        access_token: str,
        invitee_uuid: str
    ) -> Dict[str, Any]:
        """Get a specific invitee.

        Args:
            access_token: Valid Calendly access token
            invitee_uuid: Invitee UUID

        Returns:
            Invitee details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/scheduled_events/invitees/{invitee_uuid}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get invitee: {response.text}")

            return response.json().get("resource", {})

    # ============================================================================
    # Webhooks
    # ============================================================================

    async def create_webhook(
        self,
        access_token: str,
        url: str,
        events: List[str],
        organization_uri: str,
        scope: str = "organization"
    ) -> Dict[str, Any]:
        """Create a webhook subscription.

        Args:
            access_token: Valid Calendly access token
            url: Webhook callback URL
            events: List of event types to subscribe to
            organization_uri: Organization URI
            scope: Webhook scope (organization or user)

        Returns:
            Created webhook

        Raises:
            Exception: If API call fails
        """
        data = {
            "url": url,
            "events": events,
            "organization": organization_uri,
            "scope": scope
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/webhook_subscriptions",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create webhook: {response.text}")

            return response.json().get("resource", {})

    async def get_webhooks(
        self,
        access_token: str,
        organization_uri: str,
        scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get webhook subscriptions.

        Args:
            access_token: Valid Calendly access token
            organization_uri: Organization URI
            scope: Filter by scope (organization or user)

        Returns:
            List of webhooks

        Raises:
            Exception: If API call fails
        """
        params = {"organization": organization_uri}
        if scope:
            params["scope"] = scope

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/webhook_subscriptions",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get webhooks: {response.text}")

            return response.json().get("collection", [])

    async def delete_webhook(self, access_token: str, webhook_uuid: str) -> None:
        """Delete a webhook subscription.

        Args:
            access_token: Valid Calendly access token
            webhook_uuid: Webhook UUID

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}/webhook_subscriptions/{webhook_uuid}",
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to delete webhook: {response.text}")

    # ============================================================================
    # Organization
    # ============================================================================

    async def get_organization_membership(
        self,
        access_token: str,
        user_uri: str
    ) -> Dict[str, Any]:
        """Get user's organization membership.

        Args:
            access_token: Valid Calendly access token
            user_uri: User URI

        Returns:
            Organization membership

        Raises:
            Exception: If API call fails
        """
        params = {"user": user_uri}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/organization_memberships",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get organization membership: {response.text}")

            collection = response.json().get("collection", [])
            return collection[0] if collection else {}


calendly_service = CalendlyService()
