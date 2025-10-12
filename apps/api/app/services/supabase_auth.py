"""Supabase authentication service."""
import httpx
from typing import Optional, Dict, Any
import httpx
from app.config import settings


class SupabaseAuthService:
    """Service for interacting with Supabase Auth."""

    def __init__(self):
        self.base_url = f"{settings.SUPABASE_URL}/auth/v1"
        self.headers = {
            "apikey": settings.SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        }
        self.service_headers = {
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }

    async def verify_google_token(self, id_token: str) -> Dict[str, Any]:
        """Verify Google ID token with Supabase.

        Args:
            id_token: Google ID token from the client

        Returns:
            User data from Supabase

        Raises:
            httpx.HTTPError: If verification fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token",
                json={
                    "provider": "google",
                    "id_token": id_token,
                },
                headers=self.headers,
                params={"grant_type": "id_token"}
            )
            response.raise_for_status()
            return response.json()

    async def verify_apple_token(self, id_token: str) -> Dict[str, Any]:
        """Verify Apple ID token with Supabase.

        Args:
            id_token: Apple ID token from the client

        Returns:
            User data from Supabase

        Raises:
            httpx.HTTPError: If verification fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token",
                json={
                    "provider": "apple",
                    "id_token": id_token,
                },
                headers=self.headers,
                params={"grant_type": "id_token"}
            )
            response.raise_for_status()
            return response.json()

    async def get_user(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user information from Supabase using access token.

        Args:
            access_token: Supabase access token

        Returns:
            User data or None if token is invalid
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/user",
                headers={
                    **self.headers,
                    "Authorization": f"Bearer {access_token}",
                }
            )
            if response.status_code == 200:
                return response.json()
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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/token",
                json={"refresh_token": refresh_token},
                headers=self.headers,
                params={"grant_type": "refresh_token"}
            )
            response.raise_for_status()
            return response.json()

    async def sign_out(self, access_token: str) -> bool:
        """Sign out user from Supabase.

        Args:
            access_token: Supabase access token

        Returns:
            True if successful, False otherwise
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/logout",
                headers={
                    **self.headers,
                    "Authorization": f"Bearer {access_token}",
                }
            )
            return response.status_code == 204


supabase_auth_service = SupabaseAuthService()
