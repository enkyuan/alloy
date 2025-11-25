import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


async def get_valid_google_token(integration: Integration, db: Session) -> str:
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
        and integration.expires_at > datetime.utcnow() + timedelta(minutes=5)
    ):
        return integration.access_token

    logger.info(f"Refreshing Google token for user {integration.user_id}")

    if not integration.refresh_token:
        logger.error("No refresh token available for Google integration")
        raise Exception("No refresh token available")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
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
            integration.expires_at = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )
            integration.updated_at = datetime.utcnow()

            # Run blocking DB operations in a thread
            await asyncio.to_thread(db.commit)
            await asyncio.to_thread(db.refresh, integration)

            logger.info("Successfully refreshed Google token")
            return integration.access_token

    except Exception as e:
        logger.error(f"Error refreshing Google token: {e}")
        raise
