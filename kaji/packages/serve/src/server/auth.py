"""Shared JWT utilities used by serve HTTP deps and WebSocket auth paths."""

from __future__ import annotations

from typing import Any

from kaji_serve.config import settings


def decode_bearer_token(token: str) -> dict[str, Any]:
    """Decode a Supabase JWT and return the payload with 'id' set to 'sub'.

    Uses python-jose for local HS256 decode, with no network call to the
    Supabase auth API.

    Raises:
        HTTPException 401: if the token is invalid, expired, or missing a sub.
        HTTPException 503: if JWT trust settings are incomplete.
    """
    try:
        from fastapi import HTTPException, status  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "fastapi is required for HTTPException. "
            "Install it in the host package (kaji-serve already depends on it)."
        ) from exc

    secret = settings.JWT_SECRET.strip()
    issuer = settings.JWT_ISSUER.strip()
    audience = settings.JWT_AUDIENCE.strip()
    if not secret or not issuer or not audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )

    try:
        from jose import JWTError, jwt  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "python-jose is required for JWT decoding. "
            "Install it in the host package (kaji-serve already depends on it)."
        ) from exc

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={"require_iss": True, "require_aud": True},
        )
    except JWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from error

    payload = {**payload, "id": payload.get("sub")}

    if not payload.get("id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return payload
"""Supabase authentication service."""


import logging
from functools import lru_cache
from typing import Any

from kaji.core.logging import log_redacted_failure
from kaji_serve.config import get_settings
from kaji_serve.server.errors import ServiceAuthError, ServiceError
from kaji_serve.server.http import HTTPService

logger = logging.getLogger(__name__)


class SupabaseAuthService(HTTPService):
    """Service for interacting with Supabase Auth."""

    SERVICE_NAME = "supabase"

    def __init__(self) -> None:
        settings = get_settings()
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
        except ServiceAuthError as error:
            logger.warning(
                "Supabase rejected access token while fetching user (status=%s)",
                error.status_code,
            )
            return None
        except ServiceError as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Failed to get user from Supabase",
                error,
            )
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
        except ServiceError as error:
            log_redacted_failure(
                logger,
                logging.ERROR,
                "Failed to sign out user",
                error,
            )
            return False


@lru_cache(maxsize=1)
def get_supabase_auth_service() -> SupabaseAuthService:
    return SupabaseAuthService()


def __getattr__(name: str) -> Any:
    if name == "supabase_auth_service":
        return get_supabase_auth_service()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
