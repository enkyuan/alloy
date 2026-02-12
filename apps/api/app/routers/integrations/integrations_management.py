"""Generic integration management routes."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.integration import Integration
from app.schemas.integration import IntegrationListResponse, IntegrationStatusResponse
from app.services.user.auth import supabase_auth_service

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("", response_model=IntegrationListResponse)
async def get_user_integrations(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get all integrations for the authenticated user.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of user integrations

    Raises:
        HTTPException: If authentication fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get user integrations from database
        integrations = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.is_active == True,
            )
            .all()
        )

        # Map backend service names to iOS app expected names
        service_name_mapping = {
            "google_calendar": "googleCalendar",
            "spotify": "spotify",
            "gmail": "gmail",
            "uber": "uber",
            "discord": "discord",
            "todoist": "todoist",
            "calendly": "calendly",
        }

        integration_statuses = []
        for integration in integrations:
            service_key = str(integration.service)
            mapped_service = service_name_mapping.get(service_key, service_key)
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
    except Exception as e:
        logger.error(f"Failed to get integrations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get integrations: {str(e)}",
        )


@router.post("/{service}/disconnect")
async def disconnect_service(
    service: str, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Disconnect a service integration.

    Args:
        service: Service name to disconnect
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If disconnection fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Map URL path service names to database service names
        service_path_to_db_mapping = {
            "google-calendar": "google_calendar",
            "gmail": "gmail",
            "spotify": "spotify",
            "uber": "uber",
            "discord": "discord",
            "todoist": "todoist",
            "calendly": "calendly",
        }

        db_service_name = service_path_to_db_mapping.get(service, service)
        logger.info(
            f"Mapped service '{service}' to database service '{db_service_name}'"
        )

        # Find and deactivate integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == db_service_name,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active {db_service_name} integration found",
            )

        # Soft delete - set is_active to False
        integration.is_active = False
        integration.updated_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"Successfully disconnected {db_service_name} for user {supabase_user['id']}"
        )

        return {"success": True, "message": f"Successfully disconnected {service}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect {service}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect service: {str(e)}",
        )
