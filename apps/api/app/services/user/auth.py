"""Supabase authentication service."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.services.integrations.base import IntegrationHTTPService
from app.services.integrations.errors import (
    IntegrationAuthError,
    IntegrationServiceError,
)

logger = logging.getLogger(__name__)


class SupabaseAuthService(IntegrationHTTPService):
    """Service for interacting with Supabase Auth."""

    SERVICE_NAME = "supabase"

    def __init__(self) -> None:
        super().__init__(max_connections=80)
        self.base_url = f"{settings.SUPABASE_KONG_URL}/auth/v1"
        self.headers = {
            "apikey": settings.SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        }
        self.service_headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        }

    async def verify_google_token(
        self,
        id_token: str,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        # nonce is intentionally unused for iOS Google Sign-In.
        _ = nonce
        payload = {
            "provider": "google",
            "id_token": id_token,
        }
        response = await self._request_json(
            "POST",
            f"{self.base_url}/token",
            action="verify google token",
            headers=self.headers,
            params={"grant_type": "id_token"},
            json=payload,
            expected_status=(200,),
            retry_attempts=1,
        )
        logger.info("Successfully verified Google token")
        return response

    async def verify_apple_token(self, id_token: str) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            f"{self.base_url}/token",
            action="verify apple token",
            headers=self.headers,
            params={"grant_type": "id_token"},
            json={"provider": "apple", "id_token": id_token},
            expected_status=(200,),
            retry_attempts=1,
        )
        logger.info("Successfully verified Apple token")
        return response

    async def get_user(self, access_token: str) -> dict[str, Any] | None:
        try:
            response = await self._request(
                "GET",
                f"{self.base_url}/user",
                action="get user",
                headers={**self.headers, "Authorization": f"Bearer {access_token}"},
                expected_status=(200,),
                retry_attempts=1,
            )
            logger.info("Successfully retrieved user from Supabase")
            return response.json()
        except IntegrationAuthError as error:
            logger.warning(
                "Supabase rejected access token while fetching user (status=%s)",
                error.status_code,
            )
            return None
        except IntegrationServiceError as error:
            logger.error("Error getting user from Supabase: %s", error)
            raise

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            f"{self.base_url}/token",
            action="refresh token",
            headers=self.headers,
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            expected_status=(200,),
            retry_attempts=1,
        )
        logger.info("Successfully refreshed token")
        return response

    async def sign_out(self, access_token: str) -> bool:
        try:
            response = await self._request(
                "POST",
                f"{self.base_url}/logout",
                action="sign out",
                headers={**self.headers, "Authorization": f"Bearer {access_token}"},
                expected_status=(204, 401, 403),
                retry_attempts=1,
            )
            success = response.status_code == 204
            if success:
                logger.info("Successfully signed out user")
            else:
                logger.warning("Sign out returned status %s", response.status_code)
            return success
        except IntegrationServiceError as error:
            logger.error("Error signing out user: %s", error)
            return False


supabase_auth_service = SupabaseAuthService()
