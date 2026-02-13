import logging
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)

_workspace_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _workspace_http_client
    if _workspace_http_client is None:
        _workspace_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0),
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=15),
            follow_redirects=False,
        )
    return _workspace_http_client


async def close_workspace_http_client() -> None:
    global _workspace_http_client
    if _workspace_http_client is not None:
        await _workspace_http_client.aclose()
        _workspace_http_client = None


async def get_valid_google_token(
    integration: Integration, db: Session | AsyncSession
) -> str:
    """Get a valid Google access token, refreshing if necessary.

    Args:
        integration: Integration model instance
        db: Database session

    Returns:
        Valid access token

    Raises:
        Exception: If token refresh fails
    """
    # Check if token is expired or about to expire (within 5 minutes)
    if (
        integration.expires_at
        and integration.expires_at > datetime.now(timezone.utc) + timedelta(minutes=5)
    ):
        return str(integration.access_token)

    logger.info(f"Refreshing Google token for user {integration.user_id}")

    if not integration.refresh_token:
        logger.error("No refresh token available for Google integration")
        raise Exception("No refresh token available")

    try:
        response = await _get_http_client().post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": integration.refresh_token,
                "grant_type": "refresh_token",
            },
        )

        if response.status_code != 200:
            logger.error(f"Failed to refresh Google token: {response.text}")
            raise Exception(f"Token refresh failed: {response.text}")

        token_data = response.json()

        # Update integration
        integration.access_token = token_data["access_token"]
        integration.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )
        integration.updated_at = datetime.now(timezone.utc)

        if isinstance(db, AsyncSession):
            await db.commit()
            await db.refresh(integration)
        else:
            # Keep sync worker path non-blocking for async callers.
            await asyncio.to_thread(db.commit)
            await asyncio.to_thread(db.refresh, integration)

        logger.info("Successfully refreshed Google token")
        return str(integration.access_token)

    except Exception as e:
        logger.error(f"Error refreshing Google token: {e}")
        raise
