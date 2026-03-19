"""Shared FastAPI router dependencies."""

from typing import Any, Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db_session import db_execute
from app.core.database import get_db
from app.models.integration import Integration
from app.services.integrations.errors import IntegrationServiceError
from app.services.user.auth import supabase_auth_service

security = HTTPBearer()


async def get_current_supabase_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    """Validate Bearer auth and return Supabase user payload."""
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        supabase_user = {**payload, "id": payload.get("sub")}
    except JWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from error

    if not supabase_user.get("id"):
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
    result = await db_execute(
        db,
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
