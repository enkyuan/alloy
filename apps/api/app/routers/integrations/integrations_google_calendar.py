"""Google Calendar integration routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.services.integrations.workspace.gcalendar import get_google_calendar_service

from .integrations_google_shared import (
    disconnect_google_integration,
    require_google_access_token,
    require_native_google_tokens,
)
from .integrations_shared import upsert_integration

logger = logging.getLogger(__name__)
router = APIRouter()

NATIVE_GOOGLE_TOKEN_TTL = timedelta(hours=1)


from googleapiclient.errors import HttpError

async def _verify_calendar_access(access_token: str) -> str:
    try:
        calendar_svc = get_google_calendar_service(access_token)
        calendars = await asyncio.to_thread(calendar_svc.list_calendars)
        primary_calendar = next(
            (cal for cal in calendars if cal.get("id") == "primary"),
            calendars[0] if calendars else None,
        )
        calendar_email = primary_calendar.get("id") if primary_calendar else "primary"
        logger.info("Successfully verified Calendar access for %s", calendar_email)
        return str(calendar_email)
    except HTTPException:
        raise
    except HttpError as error:
        logger.warning("Calendar API error during verification: %s", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or insufficient Calendar access token. Make sure Calendar scopes were granted.",
        ) from error
    except Exception as error:
        logger.error("Unexpected error verifying Calendar access: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Calendar access",
        ) from error


@router.post("/google-calendar/connect-native")
async def connect_google_calendar_native(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect Google Calendar using native Google Sign-In SDK (iOS)."""
    try:
        body_data = await request.json()
        _, google_access_token = require_native_google_tokens(body_data)
        user_id = str(supabase_user["id"])
        calendar_email = await _verify_calendar_access(google_access_token)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="google_calendar",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) + NATIVE_GOOGLE_TOKEN_TTL,
            token_type="Bearer",
            scope="calendar.readonly calendar.events",
            overwrite_refresh_token=False,
        )

        logger.info(
            "Successfully connected Google Calendar via native SDK for user %s",
            user_id,
        )
        return {
            "success": True,
            "message": "Google Calendar connected successfully",
            "calendar_id": calendar_email,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to connect Google Calendar: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Google Calendar",
        ) from error


@router.post("/google-calendar/sync")
async def sync_google_calendar_from_google_signin(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Google Calendar integration from Google Sign-In access token (legacy)."""
    try:
        body_data = await request.json()
        google_access_token = require_google_access_token(body_data)
        user_id = str(supabase_user["id"])
        calendar_email = await _verify_calendar_access(google_access_token)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="google_calendar",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) + NATIVE_GOOGLE_TOKEN_TTL,
            token_type="Bearer",
            scope="calendar.readonly calendar.events",
            overwrite_refresh_token=False,
        )

        logger.info(
            "Successfully synced Google Calendar integration for user %s",
            user_id,
        )
        return {
            "success": True,
            "message": "Google Calendar synced successfully",
            "calendar_id": calendar_email,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to sync Google Calendar: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync Google Calendar",
        ) from error


@router.post("/google-calendar/disconnect")
async def disconnect_google_calendar(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Google Calendar integration."""
    try:
        user_id = str(supabase_user["id"])
        await disconnect_google_integration(
            db=db,
            user_id=user_id,
            service="google_calendar",
            service_name="Google Calendar",
        )
        logger.info("Successfully disconnected Google Calendar for user %s", user_id)
        return {"success": True, "message": "Google Calendar disconnected successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to disconnect Google Calendar: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect Google Calendar",
        ) from error
