"""Shared helpers for Google workspace integration routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import Integration

from .integrations_shared import get_oauth_http_client

logger = logging.getLogger(__name__)


async def revoke_google_token(access_token: str) -> None:
    """Revoke a Google OAuth token using the shared OAuth client."""
    oauth_client = await get_oauth_http_client()
    await oauth_client.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": access_token},
    )


async def disconnect_google_integration(
    *,
    db: AsyncSession,
    user_id: str,
    service: str,
    service_name: str,
) -> None:
    """Delete an existing Google integration and attempt token revocation."""
    integration_query = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == service,
        )
    )
    integration = integration_query.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{service_name} integration not found",
        )

    if integration.access_token:
        try:
            await revoke_google_token(str(integration.access_token))
            logger.info("Revoked %s token for user %s", service_name, user_id)
        except Exception as error:
            logger.warning(
                "Failed to revoke %s token for user %s: %s",
                service_name,
                user_id,
                error,
            )

    await db.delete(integration)
    await db.commit()


def require_native_google_tokens(body_data: dict[str, Any]) -> tuple[str, str]:
    """Extract required id/access token pair from request body."""
    google_id_token = str(body_data.get("id_token", "")).strip()
    google_access_token = str(body_data.get("access_token", "")).strip()
    if not google_id_token or not google_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing id_token or access_token in request body",
        )
    return google_id_token, google_access_token


def require_google_access_token(body_data: dict[str, Any]) -> str:
    """Extract required access token from request body."""
    google_access_token = str(body_data.get("access_token", "")).strip()
    if not google_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing access_token in request body",
        )
    return google_access_token
