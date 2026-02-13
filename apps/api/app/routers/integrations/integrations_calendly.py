"""Calendly integration routes."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse
from app.services.calendly import calendly_service
from app.services.integrations.errors import (
    IntegrationServiceError,
    integration_error_to_detail,
    integration_error_to_http_status,
)

from .integrations_shared import (
    exchange_oauth_code,
    persist_oauth_state,
    require_integration_token,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()
CALENDLY_DEFAULT_EXPIRES_IN_SECONDS = 7200


def _raise_integration_http_error(
    error: IntegrationServiceError,
    *,
    fallback_detail: str,
) -> None:
    raise HTTPException(
        status_code=integration_error_to_http_status(error),
        detail=integration_error_to_detail(error, fallback=fallback_detail),
    ) from error


calendly_token_dependency = require_integration_token(
    "calendly",
    not_connected_detail="Calendly not connected",
    resolver=calendly_service.get_valid_token,
)


@router.get("/calendly/auth", response_model=OAuthURLResponse)
async def get_calendly_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Calendly OAuth authorization URL."""
    try:
        if not settings.CALENDLY_CLIENT_ID or not settings.CALENDLY_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Calendly OAuth is not configured",
            )

        state = secrets.token_urlsafe(32)
        await persist_oauth_state(
            state=state, user_id=str(supabase_user["id"]), service="calendly"
        )

        params = {
            "client_id": settings.CALENDLY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.CALENDLY_REDIRECT_URI,
            "state": state,
        }
        auth_url = f"https://auth.calendly.com/oauth/authorize?{urlencode(params)}"

        logger.info("Generated Calendly OAuth URL for user %s", supabase_user["id"])
        return OAuthURLResponse(authUrl=auth_url, state=state)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate Calendly OAuth URL: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        )


@router.get("/calendly/callback")
async def calendly_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Calendly OAuth callback and redirect to iOS app."""
    redirect_url = f"havenos://calendly/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/calendly/exchange")
async def calendly_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Calendly authorization code for access token."""
    try:
        user_id = str(supabase_user["id"])
        await validate_and_consume_oauth_state(state=state, user_id=user_id)

        token_data = await exchange_oauth_code(
            token_url="https://auth.calendly.com/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.CALENDLY_REDIRECT_URI,
                "client_id": settings.CALENDLY_CLIENT_ID,
                "client_secret": settings.CALENDLY_CLIENT_SECRET,
            },
        )

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", CALENDLY_DEFAULT_EXPIRES_IN_SECONDS)
        )
        await upsert_integration(
            db=db,
            user_id=user_id,
            service="calendly",
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=token_data.get("scope"),
        )

        logger.info("Successfully connected Calendly for user %s", user_id)
        return {
            "success": True,
            "message": "Successfully connected Calendly",
            "service": "calendly",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Calendly code exchange failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to exchange code",
        )


# ============================================================================
# Calendly API Endpoints
# ============================================================================


@router.get("/calendly/events")
async def get_calendly_events(
    event_status: Optional[str] = Query(None, description="Filter by status"),
    min_start_time: Optional[str] = Query(
        None, description="Minimum start time (ISO 8601)"
    ),
    max_start_time: Optional[str] = Query(
        None, description="Maximum start time (ISO 8601)"
    ),
    count: int = Query(20, description="Number of events"),
    calendly_token: str = Depends(calendly_token_dependency),
):
    """Get Calendly scheduled events."""
    try:
        user_info = await calendly_service.get_current_user(calendly_token)
        user_uri = user_info.get("uri")
        if user_uri is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Calendly user URI not available",
            )

        events = await calendly_service.get_scheduled_events(
            calendly_token,
            user_uri=cast(str, user_uri),
            status=event_status,
            min_start_time=min_start_time,
            max_start_time=max_start_time,
            count=count,
        )
        return {"events": events}
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Calendly events fetch failed: %s", error)
        _raise_integration_http_error(error, fallback_detail="Failed to get events")
    except Exception as e:
        logger.error("Failed to get Calendly events: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get events",
        )


@router.get("/calendly/event-types")
async def get_calendly_event_types(
    active: Optional[bool] = Query(None, description="Filter by active status"),
    calendly_token: str = Depends(calendly_token_dependency),
):
    """Get Calendly event types."""
    try:
        user_info = await calendly_service.get_current_user(calendly_token)
        user_uri = user_info.get("uri")
        if user_uri is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Calendly user URI not available",
            )

        event_types = await calendly_service.get_event_types(
            calendly_token,
            user_uri=cast(str, user_uri),
            active=active,
        )
        return {"event_types": event_types}
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Calendly event types fetch failed: %s", error)
        _raise_integration_http_error(
            error,
            fallback_detail="Failed to get event types",
        )
    except Exception as e:
        logger.error("Failed to get Calendly event types: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get event types",
        )


@router.post("/calendly/events/{event_uuid}/cancel")
async def cancel_calendly_event(
    event_uuid: str,
    reason: Optional[str] = Query(None, description="Cancellation reason"),
    calendly_token: str = Depends(calendly_token_dependency),
):
    """Cancel a Calendly event."""
    try:
        await calendly_service.cancel_scheduled_event(
            calendly_token,
            event_uuid,
            reason=reason,
        )
        return {"success": True, "message": "Event cancelled"}
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Calendly event cancellation failed: %s", error)
        _raise_integration_http_error(error, fallback_detail="Failed to cancel event")
    except Exception as e:
        logger.error("Failed to cancel Calendly event: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel event",
        )
