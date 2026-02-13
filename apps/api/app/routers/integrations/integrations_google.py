"""Google workspace integration routes (Gmail and Google Calendar)."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.integration import Integration
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse
from app.services.integrations.workspace.gcalendar import get_google_calendar_service
from app.services.integrations.workspace.gmail import get_gmail_service

from .integrations_shared import (
    exchange_oauth_code,
    get_oauth_http_client,
    persist_oauth_state,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()


async def _revoke_google_token(access_token: str) -> None:
    """Revoke a Google OAuth token using the shared OAuth client."""
    oauth_client = await get_oauth_http_client()
    await oauth_client.post(
        "https://oauth2.googleapis.com/revoke",
        params={"token": access_token},
    )

# =======================
# Gmail Integration Routes
# =======================


@router.get("/gmail/auth", response_model=OAuthURLResponse)
async def get_gmail_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Gmail OAuth authorization URL.

    Args:
        supabase_user: Authenticated Supabase user payload

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Gmail is not configured
    """
    try:
        # Check if Gmail is configured
        if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gmail OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        await persist_oauth_state(
            state=state,
            user_id=str(supabase_user["id"]),
            service="gmail",
        )

        # Build Google OAuth URL with Gmail scopes
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/userinfo.email",
        ]

        params = {
            "client_id": settings.GMAIL_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.GMAIL_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",  # Request refresh token
            "prompt": "consent",  # Force consent screen to get refresh token
        }

        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

        logger.info(f"Generated Gmail OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Gmail OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        )


@router.post("/gmail/exchange")
async def gmail_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Gmail authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Google
        state: State parameter for CSRF protection
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If exchange fails
    """
    try:
        user_id = str(supabase_user["id"])
        await validate_and_consume_oauth_state(state=state, user_id=user_id)

        token_data = await exchange_oauth_code(
            token_url="https://oauth2.googleapis.com/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.GMAIL_REDIRECT_URI,
                "client_id": settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
            },
            failure_detail="Failed to exchange authorization code",
        )
        gmail_access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        if not gmail_access_token:
            logger.error("No access token in Gmail response")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token received from Google",
            )

        # Get user's Gmail profile to verify the connection
        gmail_svc = get_gmail_service(gmail_access_token, refresh_token)
        profile = gmail_svc.get_profile()
        gmail_email = profile.get("emailAddress")

        logger.info(f"Successfully authenticated Gmail for {gmail_email}")

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=gmail_access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope") or "gmail.readonly gmail.send gmail.modify",
            overwrite_refresh_token=False,
        )

        logger.info(f"Successfully stored Gmail integration for user {user_id}")

        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to exchange Gmail code: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Gmail",
        )


@router.post("/gmail/connect-native")
async def connect_gmail_native(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect Gmail using native Google Sign-In SDK (iOS).

    This endpoint receives ID token and access token from Google Sign-In SDK
    and stores them for Gmail API access. This bypasses the loopback flow
    that Google has deprecated.

    Args:
        request: FastAPI request object with id_token and access_token
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If connection fails
    """
    try:
        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body",
            )

        user_id = str(supabase_user["id"])

        # Verify token works with Gmail API and get user's email
        try:
            gmail_svc = get_gmail_service(google_access_token)
            profile = gmail_svc.get_profile()
            gmail_email = profile.get("emailAddress")
            logger.info(f"Successfully verified Gmail access for {gmail_email}")
        except Exception as e:
            logger.error(f"Failed to verify Gmail access: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or insufficient Gmail access token. Make sure Gmail scopes were granted.",
            )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=token_expires_at,
            token_type="Bearer",
            scope="gmail.readonly gmail.send",
            overwrite_refresh_token=False,
        )

        logger.info(f"Successfully connected Gmail via native SDK for user {user_id}")

        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Gmail",
        )


@router.post("/gmail/sync")
async def sync_gmail_from_google_signin(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Gmail integration from Google Sign-In access token (legacy).

    This endpoint is called automatically when a user signs in with Google
    and has granted Gmail scopes. The iOS app sends the Google OAuth access
    token, and we store it for Gmail API access.

    Note: This is deprecated in favor of /gmail/connect-native which uses
    the native Google Sign-In SDK flow.

    Args:
        request: FastAPI request object
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If sync fails
    """
    try:
        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body",
            )

        user_id = str(supabase_user["id"])

        # Verify token works with Gmail API and get user's email
        try:
            gmail_svc = get_gmail_service(google_access_token)
            profile = gmail_svc.get_profile()
            gmail_email = profile.get("emailAddress")
            logger.info(f"Successfully verified Gmail access for {gmail_email}")
        except Exception as e:
            logger.error(f"Failed to verify Gmail access: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or insufficient Gmail access token",
            )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=token_expires_at,
            token_type="Bearer",
            scope="gmail.readonly gmail.send gmail.modify",
            overwrite_refresh_token=False,
        )

        logger.info(f"Successfully synced Gmail integration for user {user_id}")

        return {
            "success": True,
            "message": "Gmail synced successfully",
            "email": gmail_email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync Gmail",
        )


@router.post("/gmail/disconnect")
async def disconnect_gmail(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Gmail integration.

    Args:
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If not authenticated or disconnection fails
    """
    try:
        user_id = str(supabase_user["id"])
        # Find Gmail integration
        integration_query = await db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.service == "gmail",
            )
        )
        integration = integration_query.scalar_one_or_none()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gmail integration not found",
            )

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                await _revoke_google_token(str(integration.access_token))
                logger.info(f"Revoked Gmail token for user {user_id}")
            except Exception as e:
                logger.warning(f"Failed to revoke Gmail token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        await db.delete(integration)
        await db.commit()

        logger.info(f"Successfully disconnected Gmail for user {user_id}")

        return {"success": True, "message": "Gmail disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect Gmail",
        )


# =======================
# Google Calendar Integration Routes
# =======================


@router.post("/google-calendar/connect-native")
async def connect_google_calendar_native(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect Google Calendar using native Google Sign-In SDK (iOS).

    This endpoint receives ID token and access token from Google Sign-In SDK
    and stores them for Calendar API access. This bypasses the loopback flow
    that Google has deprecated.

    Args:
        request: FastAPI request object with id_token and access_token
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If connection fails
    """
    try:
        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body",
            )

        user_id = str(supabase_user["id"])

        # Verify token works with Calendar API and get user's calendars
        try:
            calendar_svc = get_google_calendar_service(google_access_token)
            calendars = calendar_svc.list_calendars()
            primary_calendar = next(
                (cal for cal in calendars if cal.get("id") == "primary"),
                calendars[0] if calendars else None,
            )
            calendar_email = (
                primary_calendar.get("id") if primary_calendar else "primary"
            )
            logger.info(f"Successfully verified Calendar access for {calendar_email}")
        except Exception as e:
            logger.error(f"Failed to verify Calendar access: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or insufficient Calendar access token. Make sure Calendar scopes were granted.",
            )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="google_calendar",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=token_expires_at,
            token_type="Bearer",
            scope="calendar.readonly calendar.events",
            overwrite_refresh_token=False,
        )

        logger.info(
            f"Successfully connected Google Calendar via native SDK for user {user_id}"
        )

        return {
            "success": True,
            "message": "Google Calendar connected successfully",
            "calendar_id": calendar_email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Google Calendar",
        )


@router.post("/google-calendar/sync")
async def sync_google_calendar_from_google_signin(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Google Calendar integration from Google Sign-In access token (legacy).

    This endpoint is called automatically when a user signs in with Google
    and has granted Calendar scopes. The iOS app sends the Google OAuth access
    token, and we store it for Calendar API access.

    Note: This is deprecated in favor of /google-calendar/connect-native which uses
    the native Google Sign-In SDK flow.

    Args:
        request: FastAPI request object
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If sync fails
    """
    try:
        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body",
            )

        user_id = str(supabase_user["id"])

        # Verify token works with Calendar API and get user's calendars
        try:
            calendar_svc = get_google_calendar_service(google_access_token)
            calendars = calendar_svc.list_calendars()
            primary_calendar = next(
                (cal for cal in calendars if cal.get("id") == "primary"),
                calendars[0] if calendars else None,
            )
            calendar_email = (
                primary_calendar.get("id") if primary_calendar else "primary"
            )
            logger.info(f"Successfully verified Calendar access for {calendar_email}")
        except Exception as e:
            logger.error(f"Failed to verify Calendar access: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or insufficient Calendar access token",
            )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="google_calendar",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=token_expires_at,
            token_type="Bearer",
            scope="calendar.readonly calendar.events",
            overwrite_refresh_token=False,
        )

        logger.info(
            f"Successfully synced Google Calendar integration for user {user_id}"
        )

        return {
            "success": True,
            "message": "Google Calendar synced successfully",
            "calendar_id": calendar_email,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync Google Calendar",
        )


@router.post("/google-calendar/disconnect")
async def disconnect_google_calendar(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Google Calendar integration.

    Args:
        supabase_user: Authenticated Supabase user payload
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If not authenticated or disconnection fails
    """
    try:
        user_id = str(supabase_user["id"])
        # Find Google Calendar integration
        integration_query = await db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.service == "google_calendar",
            )
        )
        integration = integration_query.scalar_one_or_none()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Google Calendar integration not found",
            )

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                await _revoke_google_token(str(integration.access_token))
                logger.info(
                    f"Revoked Google Calendar token for user {user_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to revoke Google Calendar token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        await db.delete(integration)
        await db.commit()

        logger.info(
            f"Successfully disconnected Google Calendar for user {user_id}"
        )

        return {"success": True, "message": "Google Calendar disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect Google Calendar",
        )
