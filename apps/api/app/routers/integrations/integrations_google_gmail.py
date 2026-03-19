"""Gmail integration routes."""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from googleapiclient.errors import HttpError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse
from app.services.integrations.workspace.gmail import get_gmail_service

from .integrations_google_shared import (
    disconnect_google_integration,
    require_google_access_token,
    require_native_google_tokens,
)
from .integrations_shared import (
    exchange_oauth_code,
    persist_oauth_state,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
)
NATIVE_GOOGLE_TOKEN_TTL = timedelta(hours=1)


async def _verify_gmail_access(access_token: str) -> str:
    try:
        gmail_svc = get_gmail_service(access_token)
        profile = await asyncio.to_thread(gmail_svc.get_profile)
        gmail_email = profile.get("emailAddress")
        logger.info("Successfully verified Gmail access for %s", gmail_email)
        return str(gmail_email)
    except HTTPException:
        raise
    except HttpError as error:
        logger.warning("Gmail API error during verification: %s", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or insufficient Gmail access token. Make sure Gmail scopes were granted.",
        ) from error
    except Exception as error:
        logger.error("Unexpected error verifying Gmail access: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify Gmail access",
        ) from error


@router.get("/gmail/auth", response_model=OAuthURLResponse)
async def get_gmail_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Gmail OAuth authorization URL."""
    try:
        if (
            not settings.GMAIL_CLIENT_ID
            or not settings.GMAIL_CLIENT_SECRET
            or not settings.GMAIL_REDIRECT_URI
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gmail OAuth is not configured",
            )

        state = secrets.token_urlsafe(32)
        await persist_oauth_state(
            state=state,
            user_id=str(supabase_user["id"]),
            service="gmail",
        )
        params = {
            "client_id": settings.GMAIL_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.GMAIL_REDIRECT_URI,
            "scope": " ".join(GMAIL_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        logger.info("Generated Gmail OAuth URL for user %s", supabase_user["id"])
        return OAuthURLResponse(authUrl=auth_url, state=state)
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to generate Gmail OAuth URL: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        ) from error


@router.post("/gmail/exchange")
async def gmail_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Gmail authorization code for access token."""
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
        if not gmail_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token received from Google",
            )

        gmail_email = await _verify_gmail_access(str(gmail_access_token))
        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=str(gmail_access_token),
            refresh_token=token_data.get("refresh_token"),
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=int(token_data.get("expires_in", 3600))),
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope") or "gmail.readonly gmail.send gmail.modify",
            overwrite_refresh_token=False,
        )

        logger.info("Successfully stored Gmail integration for user %s", user_id)
        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to exchange Gmail code: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Gmail",
        ) from error


@router.post("/gmail/connect-native")
async def connect_gmail_native(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect Gmail using native Google Sign-In SDK (iOS)."""
    try:
        body_data = await request.json()
        _, google_access_token = require_native_google_tokens(body_data)
        user_id = str(supabase_user["id"])
        gmail_email = await _verify_gmail_access(google_access_token)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) + NATIVE_GOOGLE_TOKEN_TTL,
            token_type="Bearer",
            scope="gmail.readonly gmail.send",
            overwrite_refresh_token=False,
        )

        logger.info("Successfully connected Gmail via native SDK for user %s", user_id)
        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to connect Gmail: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect Gmail",
        ) from error


@router.post("/gmail/sync")
async def sync_gmail_from_google_signin(
    request: Request,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Gmail integration from Google Sign-In access token (legacy)."""
    try:
        body_data = await request.json()
        google_access_token = require_google_access_token(body_data)
        user_id = str(supabase_user["id"])
        gmail_email = await _verify_gmail_access(google_access_token)

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            access_token=google_access_token,
            refresh_token=None,
            expires_at=datetime.now(timezone.utc) + NATIVE_GOOGLE_TOKEN_TTL,
            token_type="Bearer",
            scope="gmail.readonly gmail.send gmail.modify",
            overwrite_refresh_token=False,
        )

        logger.info("Successfully synced Gmail integration for user %s", user_id)
        return {
            "success": True,
            "message": "Gmail synced successfully",
            "email": gmail_email,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to sync Gmail: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync Gmail",
        ) from error


@router.post("/gmail/disconnect")
async def disconnect_gmail(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Gmail integration."""
    try:
        user_id = str(supabase_user["id"])
        await disconnect_google_integration(
            db=db,
            user_id=user_id,
            service="gmail",
            service_name="Gmail",
        )
        logger.info("Successfully disconnected Gmail for user %s", user_id)
        return {"success": True, "message": "Gmail disconnected successfully"}
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Failed to disconnect Gmail: %s", error, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect Gmail",
        ) from error
