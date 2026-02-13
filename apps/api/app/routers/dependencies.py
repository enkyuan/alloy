"""Shared FastAPI router dependencies."""

from typing import Any, Awaitable, Callable

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.integration import Integration
from app.services.user.auth import supabase_auth_service


async def get_current_supabase_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Validate Bearer auth and return Supabase user payload."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    access_token = authorization.replace("Bearer ", "", 1)
    supabase_user = await supabase_auth_service.get_user(access_token)
    if not supabase_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return supabase_user


async def get_active_integration(
    *,
    db: AsyncSession,
    user_id: str,
    service: str,
    not_connected_detail: str,
) -> Integration:
    """Resolve an active integration for a user and service."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == service,
            Integration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_connected_detail,
        )
    return integration


def require_active_integration(
    service: str,
    *,
    not_connected_detail: str,
) -> Callable[..., Awaitable[Integration]]:
    """Build a dependency that returns an active integration for the authed user."""

    async def _dependency(
        supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
        db: AsyncSession = Depends(get_db),
    ) -> Integration:
        user_id = str(supabase_user["id"])
        return await get_active_integration(
            db=db,
            user_id=user_id,
            service=service,
            not_connected_detail=not_connected_detail,
        )

    return _dependency
