"""Calendly integration routes."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, cast
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.integration import Integration
from app.schemas.integration import OAuthURLResponse
from app.services.user.auth import supabase_auth_service

from .integrations_shared import OAUTH_STATE_TTL, redis_client

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/calcom/connect")
# ============================================================================
# Calendly Integration Routes
# ============================================================================

@router.get("/calendly/auth", response_model=OAuthURLResponse)
async def get_calendly_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Calendly OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Calendly is not configured
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("Missing or invalid authorization header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            logger.warning("Invalid or expired token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Check if Calendly is configured
        if not settings.CALENDLY_CLIENT_ID or not settings.CALENDLY_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Calendly OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "calendly",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
        )

        # Build Calendly OAuth URL
        params = {
            "client_id": settings.CALENDLY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.CALENDLY_REDIRECT_URI,
            "state": state,
        }

        auth_url = f"https://auth.calendly.com/oauth/authorize?{urlencode(params)}"

        logger.info(f"Generated Calendly OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Calendly OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.get("/calendly/callback")
async def calendly_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Calendly OAuth callback and redirect to iOS app.

    This endpoint receives the OAuth callback from Calendly and redirects
    to the iOS app with the code and state parameters.

    Args:
        code: Authorization code from Calendly
        state: State parameter for CSRF protection

    Returns:
        Redirect to iOS app with code and state
    """
    # Redirect to iOS app with code and state
    redirect_url = f"havenos://calendly/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/calendly/exchange")
async def calendly_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Calendly authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Calendly
        state: State parameter for CSRF protection
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If exchange fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)

        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter",
            )

        # Verify state belongs to this user
        state_data = json.loads(state_json)
        if state_data["user_id"] != supabase_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="State parameter does not match user",
            )

        # Delete state from Redis (one-time use)
        await redis_client.delete(state_key)

        user_id = supabase_user["id"]

        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://auth.calendly.com/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.CALENDLY_REDIRECT_URI,
                    "client_id": settings.CALENDLY_CLIENT_ID,
                    "client_secret": settings.CALENDLY_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Calendly token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()

        # Calculate token expiration
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 7200)
        )

        # Check if integration already exists
        existing_integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "calendly")
            .first()
        )

        if existing_integration:
            # Update existing integration
            existing_integration.access_token = token_data["access_token"]
            existing_integration.refresh_token = token_data.get("refresh_token")
            existing_integration.token_type = token_data.get("token_type", "Bearer")
            existing_integration.expires_at = expires_at
            existing_integration.scope = token_data.get("scope")
            existing_integration.is_active = True
            existing_integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="calendly",
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_type=token_data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scope=token_data.get("scope"),
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Calendly for user {user_id}")

        return {
            "success": True,
            "message": "Successfully connected Calendly",
            "service": "calendly",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendly code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}",
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
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Get Calendly scheduled events.

    Args:
        status: Filter by status (active, canceled)
        min_start_time: Minimum start time
        max_start_time: Maximum start time
        count: Number of events
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of scheduled events

    Raises:
        HTTPException: If not authenticated or Calendly not connected
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

        # Get Calendly integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "calendly",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Calendly not connected"
            )

        # Import calendly service
        from app.services.calendly import calendly_service

        # Get valid token
        calendly_token = await calendly_service.get_valid_token(integration, db)

        # Get current user to get user URI
        user_info = await calendly_service.get_current_user(calendly_token)
        user_uri = user_info.get("uri")
        if user_uri is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Calendly user URI not available",
            )
        user_uri = cast(str, user_uri)

        # Get events
        events = await calendly_service.get_scheduled_events(
            calendly_token,
            user_uri=user_uri,
            status=event_status,
            min_start_time=min_start_time,
            max_start_time=max_start_time,
            count=count,
        )

        return {"events": events}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Calendly events: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get events: {str(e)}",
        )


@router.get("/calendly/event-types")
async def get_calendly_event_types(
    active: Optional[bool] = Query(None, description="Filter by active status"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Get Calendly event types.

    Args:
        active: Filter by active status
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of event types

    Raises:
        HTTPException: If not authenticated or Calendly not connected
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

        # Get Calendly integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "calendly",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Calendly not connected"
            )

        # Import calendly service
        from app.services.calendly import calendly_service

        # Get valid token
        calendly_token = await calendly_service.get_valid_token(integration, db)

        # Get current user to get user URI
        user_info = await calendly_service.get_current_user(calendly_token)
        user_uri = user_info.get("uri")
        if user_uri is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Calendly user URI not available",
            )
        user_uri = cast(str, user_uri)

        # Get event types
        event_types = await calendly_service.get_event_types(
            calendly_token, user_uri=user_uri, active=active
        )

        return {"event_types": event_types}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Calendly event types: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get event types: {str(e)}",
        )


@router.post("/calendly/events/{event_uuid}/cancel")
async def cancel_calendly_event(
    event_uuid: str,
    reason: Optional[str] = Query(None, description="Cancellation reason"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Cancel a Calendly event.

    Args:
        event_uuid: Event UUID
        reason: Cancellation reason
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not authenticated or Calendly not connected
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

        # Get Calendly integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "calendly",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Calendly not connected"
            )

        # Import calendly service
        from app.services.calendly import calendly_service

        # Get valid token
        calendly_token = await calendly_service.get_valid_token(integration, db)

        # Cancel event
        await calendly_service.cancel_scheduled_event(
            calendly_token, event_uuid, reason=reason
        )

        return {"success": True, "message": "Event cancelled"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel Calendly event: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel event: {str(e)}",
        )
