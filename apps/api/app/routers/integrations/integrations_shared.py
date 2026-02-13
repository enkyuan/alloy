"""Shared helpers and dependencies for integration router modules."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis_client
from app.models.integration import Integration
from app.routers.dependencies import require_active_integration
from app.services.integrations.errors import (
    IntegrationServiceError,
    integration_error_to_detail,
    integration_error_to_http_status,
)

logger = logging.getLogger(__name__)

# OAuth state TTL in seconds (15 minutes)
OAUTH_STATE_TTL = 900

_oauth_http_client: httpx.AsyncClient | None = None


async def get_oauth_redis_client():
    """Get shared Redis client for OAuth state storage."""
    return await get_redis_client()


async def get_oauth_http_client() -> httpx.AsyncClient:
    """Get shared HTTP client for OAuth token exchange requests."""
    global _oauth_http_client
    if _oauth_http_client is None:
        _oauth_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )
    return _oauth_http_client


async def close_oauth_http_client() -> None:
    """Close shared OAuth HTTP client."""
    global _oauth_http_client
    if _oauth_http_client is not None:
        await _oauth_http_client.aclose()
        _oauth_http_client = None


async def persist_oauth_state(*, state: str, user_id: str, service: str) -> None:
    """Persist OAuth state for a service/user pair in Redis."""
    state_data = {
        "user_id": user_id,
        "service": service,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    oauth_redis = await get_oauth_redis_client()
    await oauth_redis.setex(f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data))


async def validate_and_consume_oauth_state(*, state: str, user_id: str) -> dict[str, Any]:
    """Validate OAuth state ownership and consume it (single-use)."""
    state_key = f"oauth_state:{state}"
    oauth_redis = await get_oauth_redis_client()
    state_json = await oauth_redis.get(state_key)
    if not state_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    state_data = json.loads(state_json)
    if state_data.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="State parameter does not match user",
        )

    await oauth_redis.delete(state_key)
    return state_data


async def exchange_oauth_code(
    *,
    token_url: str,
    form_data: dict[str, Any],
    failure_detail: str = "Failed to exchange authorization code",
) -> dict[str, Any]:
    """Exchange OAuth auth code for access token data using shared HTTP client."""
    client = await get_oauth_http_client()
    response = await client.post(
        token_url,
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        logger.error(
            "OAuth token exchange failed",
            extra={
                "token_url": token_url,
                "status_code": response.status_code,
            },
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=failure_detail)
    return response.json()


async def upsert_integration(
    *,
    db: AsyncSession,
    user_id: str,
    service: str,
    access_token: str,
    expires_at: datetime | None,
    refresh_token: str | None = None,
    token_type: str | None = None,
    scope: str | None = None,
    overwrite_refresh_token: bool = True,
) -> Integration:
    """Create or update an integration row and commit."""
    query = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == service,
        )
    )
    integration = query.scalar_one_or_none()
    if integration is None:
        integration = Integration(
            id=str(uuid.uuid4()),
            user_id=user_id,
            service=service,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type or "Bearer",
            expires_at=expires_at,
            scope=scope,
            is_active=True,
        )
        db.add(integration)
    else:
        integration.access_token = access_token
        integration.expires_at = expires_at
        integration.is_active = True
        integration.updated_at = datetime.now(timezone.utc)
        if overwrite_refresh_token or refresh_token is not None:
            integration.refresh_token = refresh_token
        if token_type is not None:
            integration.token_type = token_type
        integration.scope = scope

    await db.commit()
    return integration


TokenResolver = Callable[[Integration, AsyncSession], Awaitable[str]]


def require_integration_token(
    service: str,
    *,
    not_connected_detail: str,
    resolver: TokenResolver,
) -> Callable[..., Awaitable[str]]:
    """Build a dependency that resolves a valid service access token."""
    integration_dep = require_active_integration(
        service,
        not_connected_detail=not_connected_detail,
    )

    async def _dependency(
        integration: Integration = Depends(integration_dep),
        db: AsyncSession = Depends(get_db),
    ) -> str:
        try:
            return await resolver(integration, db)
        except IntegrationServiceError as error:
            logger.warning(
                "Failed to resolve integration token for %s: %s",
                service,
                error,
            )
            raise HTTPException(
                status_code=integration_error_to_http_status(error),
                detail=integration_error_to_detail(
                    error,
                    fallback=f"Failed to authorize {service} integration",
                ),
            ) from error

    return _dependency
