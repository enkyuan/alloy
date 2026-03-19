"""Calendly API service."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.services.integrations.base import ExpiringOAuthIntegrationService


class CalendlyService(ExpiringOAuthIntegrationService):
    """Service for Calendly API operations."""

    SERVICE_NAME = "calendly"
    BASE_URL = settings.CALENDLY_API_BASE_URL
    TOKEN_URL = "https://auth.calendly.com/oauth/token"
    DEFAULT_EXPIRES_IN_SECONDS = 7200
    TOKEN_REFRESH_WINDOW = timedelta(minutes=5)

    def _oauth_client_credentials(self) -> tuple[str | None, str | None]:
        return settings.CALENDLY_CLIENT_ID, settings.CALENDLY_CLIENT_SECRET

    async def get_current_user(self, access_token: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/users/me",
            action="get current user",
            headers=self._auth_headers(access_token),
            response_key="resource",
            default={},
        )

    async def get_event_types(
        self,
        access_token: str,
        user_uri: str,
        active: bool | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"user": user_uri}
        if active is not None:
            params["active"] = str(active).lower()
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/event_types",
            action="get event types",
            headers=self._auth_headers(access_token),
            params=params,
            response_key="collection",
            default=[],
        )

    async def get_event_type(
        self,
        access_token: str,
        event_type_uuid: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/event_types/{event_type_uuid}",
            action="get event type",
            headers=self._auth_headers(access_token),
            response_key="resource",
            default={},
        )

    async def get_scheduled_events(
        self,
        access_token: str,
        user_uri: str | None = None,
        organization_uri: str | None = None,
        status: str | None = None,
        min_start_time: str | None = None,
        max_start_time: str | None = None,
        count: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"count": count}
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
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/scheduled_events",
            action="get scheduled events",
            headers=self._auth_headers(access_token),
            params=params,
            response_key="collection",
            default=[],
        )

    async def get_scheduled_event(
        self,
        access_token: str,
        event_uuid: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/scheduled_events/{event_uuid}",
            action="get scheduled event",
            headers=self._auth_headers(access_token),
            response_key="resource",
            default={},
        )

    async def cancel_scheduled_event(
        self,
        access_token: str,
        event_uuid: str,
        reason: str | None = None,
    ) -> None:
        data: dict[str, Any] = {}
        if reason:
            data["reason"] = reason
        await self._request_no_content(
            "POST",
            f"{self.BASE_URL}/scheduled_events/{event_uuid}/cancellation",
            action="cancel scheduled event",
            headers=self._auth_headers(access_token),
            json=data if data else None,
            expected_status=(200, 201),
        )

    async def get_event_invitees(
        self,
        access_token: str,
        event_uuid: str,
        status: str | None = None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"count": count}
        if status:
            params["status"] = status
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/scheduled_events/{event_uuid}/invitees",
            action="get event invitees",
            headers=self._auth_headers(access_token),
            params=params,
            response_key="collection",
            default=[],
        )

    async def get_invitee(
        self,
        access_token: str,
        invitee_uuid: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/scheduled_events/invitees/{invitee_uuid}",
            action="get invitee",
            headers=self._auth_headers(access_token),
            response_key="resource",
            default={},
        )

    async def create_webhook(
        self,
        access_token: str,
        url: str,
        events: list[str],
        organization_uri: str,
        scope: str = "organization",
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/webhook_subscriptions",
            action="create webhook",
            headers=self._auth_headers(access_token),
            json={
                "url": url,
                "events": events,
                "organization": organization_uri,
                "scope": scope,
            },
            expected_status=(200, 201),
            response_key="resource",
            default={},
        )

    async def get_webhooks(
        self,
        access_token: str,
        organization_uri: str,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"organization": organization_uri}
        if scope:
            params["scope"] = scope
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/webhook_subscriptions",
            action="get webhooks",
            headers=self._auth_headers(access_token),
            params=params,
            response_key="collection",
            default=[],
        )

    async def delete_webhook(self, access_token: str, webhook_uuid: str) -> None:
        await self._request_no_content(
            "DELETE",
            f"{self.BASE_URL}/webhook_subscriptions/{webhook_uuid}",
            action="delete webhook",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def get_organization_membership(
        self,
        access_token: str,
        user_uri: str,
    ) -> dict[str, Any]:
        memberships = await self._request_json(
            "GET",
            f"{self.BASE_URL}/organization_memberships",
            action="get organization membership",
            headers=self._auth_headers(access_token),
            params={"user": user_uri},
            response_key="collection",
            default=[],
        )
        if not isinstance(memberships, list):
            return {}
        return memberships[0] if memberships else {}


calendly_service = CalendlyService()
