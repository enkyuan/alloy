"""Supabase authentication service."""

import logging
from typing import Optional, Dict, Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SupabaseAuthService:
    """Service for interacting with Supabase Auth."""

    def __init__(self):
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
        self, id_token: str, nonce: Optional[str] = None
    ) -> Dict[str, Any]:
        """Verify Google ID token with Supabase.

        Args:
            id_token: Google ID token from the client
            nonce: Optional nonce used in Google Sign-In (not used for iOS Google Sign-In)

        Returns:
            User data from Supabase

        Raises:
            httpx.HTTPError: If verification fails
        """
        # For iOS Google Sign-In, we don't pass the nonce because the SDK
        # generates it internally and Supabase can't validate it
        payload = {
            "provider": "google",
            "id_token": id_token,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/token",
                    json=payload,
                    headers=self.headers,
                    params={"grant_type": "id_token"},
                )
                response.raise_for_status()
                logger.info("Successfully verified Google token")
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to verify Google token: {str(e)}")
            raise

    async def verify_apple_token(self, id_token: str) -> Dict[str, Any]:
        """Verify Apple ID token with Supabase.

        Args:
            id_token: Apple ID token from the client

        Returns:
            User data from Supabase

        Raises:
            httpx.HTTPError: If verification fails
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/token",
                    json={
                        "provider": "apple",
                        "id_token": id_token,
                    },
                    headers=self.headers,
                    params={"grant_type": "id_token"},
                )
                response.raise_for_status()
                logger.info("Successfully verified Apple token")
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to verify Apple token: {str(e)}")
            raise

    async def get_user(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user information from Supabase using access token.

        Args:
            access_token: Supabase access token

        Returns:
            User data or None if token is invalid
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/user",
                    headers={
                        **self.headers,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                if response.status_code == 200:
                    logger.info("Successfully retrieved user from Supabase")
                    return response.json()
                logger.warning(f"Failed to get user: status {response.status_code}")
                return None
        except httpx.HTTPError as e:
            logger.error(f"Error getting user from Supabase: {str(e)}")
            return None

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Supabase refresh token

        Returns:
            New token data

        Raises:
            httpx.HTTPError: If refresh fails
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/token",
                    json={"refresh_token": refresh_token},
                    headers=self.headers,
                    params={"grant_type": "refresh_token"},
                )
                response.raise_for_status()
                logger.info("Successfully refreshed token")
                return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Failed to refresh token: {str(e)}")
            raise

    async def sign_out(self, access_token: str) -> bool:
        """Sign out user from Supabase.

        Args:
            access_token: Supabase access token

        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/logout",
                    headers={
                        **self.headers,
                        "Authorization": f"Bearer {access_token}",
                    },
                )
                success = response.status_code == 204
                if success:
                    logger.info("Successfully signed out user")
                else:
                    logger.warning(f"Sign out returned status {response.status_code}")
                return success
        except httpx.HTTPError as e:
            logger.error(f"Error signing out user: {str(e)}")
            return False


supabase_auth_service = SupabaseAuthService()
