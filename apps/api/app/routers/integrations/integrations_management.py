"""Generic integration management routes."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.integration import Integration
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import IntegrationListResponse, IntegrationStatusResponse
from app.services.integrations.service_names import (
    to_client_service_name,
    to_db_service_name,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=IntegrationListResponse)
async def get_user_integrations(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all integrations for the authenticated user.

    Args:
        supabase_user: Authenticated user from Supabase dependency
        db: Database session

    Returns:
        List of user integrations

    Raises:
        HTTPException: If authentication fails
    """
    try:
        # Get user integrations from database
        query = await db.execute(
            select(Integration).where(
                Integration.user_id == supabase_user["id"],
                Integration.is_active.is_(True),
            )
        )
        integrations = query.scalars().all()

        integration_statuses = []
        for integration in integrations:
            service_key = str(integration.service)
            mapped_service = to_client_service_name(service_key)
            integration_statuses.append(
                IntegrationStatusResponse(
                    service=mapped_service,
                    connected=True,
                    connected_at=integration.created_at.isoformat()
                    if integration.created_at
                    else None,
                )
            )

        return IntegrationListResponse(integrations=integration_statuses)

    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to get integrations: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get integrations",
        ) from error


@router.post("/{service}/disconnect")
async def disconnect_service(
    service: str,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect a service integration.

    Args:
        service: Service name to disconnect
        supabase_user: Authenticated user from Supabase dependency
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If disconnection fails
    """
    try:
        db_service_name = to_db_service_name(service)
        logger.info(
            "Mapped service '%s' to database service '%s'",
            service,
            db_service_name,
        )

        # Find and deactivate integration
        query = await db.execute(
            select(Integration).where(
                Integration.user_id == supabase_user["id"],
                Integration.service == db_service_name,
            )
        )
        integration = query.scalar_one_or_none()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active {db_service_name} integration found",
            )

        # Soft delete - set is_active to False
        integration.is_active = False
        integration.updated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            "Successfully disconnected %s for user %s",
            db_service_name,
            supabase_user["id"],
        )

        return {"success": True, "message": f"Successfully disconnected {service}"}

    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to disconnect %s: %s", service, error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect service",
        ) from error
