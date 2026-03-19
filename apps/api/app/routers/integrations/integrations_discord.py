"""Discord integration routes."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse
from app.services.discord import discord_service
from app.services.integrations.errors import IntegrationServiceError

from .integrations_shared import (
    exchange_oauth_code,
    persist_oauth_state,
    raise_integration_http_error,
    require_integration_token,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()
DISCORD_DEFAULT_EXPIRES_IN_SECONDS = 604800


discord_token_dependency = require_integration_token(
    "discord",
    not_connected_detail="Discord not connected",
    resolver=discord_service.get_valid_token,
)


@router.get("/discord/auth", response_model=OAuthURLResponse)
async def get_discord_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Discord OAuth authorization URL."""
    try:
        if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Discord OAuth is not configured",
            )

        state = secrets.token_urlsafe(32)
        await persist_oauth_state(
            state=state, user_id=str(supabase_user["id"]), service="discord"
        )

        scopes = ["identify", "guilds", "guilds.members.read", "messages.read"]
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
        }
        auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"

        logger.info("Generated Discord OAuth URL for user %s", supabase_user["id"])
        return OAuthURLResponse(authUrl=auth_url, state=state)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate Discord OAuth URL: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        )


@router.get("/discord/callback")
async def discord_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Discord OAuth callback and redirect to iOS app."""
    logger.info("Discord OAuth callback received")
    redirect_url = f"havenos://discord/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/discord/exchange")
async def discord_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Discord authorization code for access token."""
    try:
        user_id = str(supabase_user["id"])
        await validate_and_consume_oauth_state(state=state, user_id=user_id)

        token_data = await exchange_oauth_code(
            token_url="https://discord.com/api/oauth2/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.DISCORD_REDIRECT_URI,
                "client_id": settings.DISCORD_CLIENT_ID,
                "client_secret": settings.DISCORD_CLIENT_SECRET,
            },
        )

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", DISCORD_DEFAULT_EXPIRES_IN_SECONDS)
        )
        await upsert_integration(
            db=db,
            user_id=user_id,
            service="discord",
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=token_data.get("scope"),
        )

        logger.info("Successfully connected Discord for user %s", user_id)
        return {
            "success": True,
            "message": "Successfully connected Discord",
            "service": "discord",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Discord code exchange failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to exchange code",
        )


# ============================================================================
# Discord API Endpoints
# ============================================================================


@router.get("/discord/profile")
async def get_discord_profile(
    discord_token: str = Depends(discord_token_dependency),
):
    """Get Discord user profile."""
    try:
        profile = await discord_service.get_current_user(discord_token)
        return profile
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Discord profile fetch failed: %s", error)
        raise_integration_http_error(error, fallback_detail="Failed to get profile")
    except Exception as e:
        logger.error("Failed to get Discord profile: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get profile",
        )


@router.get("/discord/guilds")
async def get_discord_guilds(
    discord_token: str = Depends(discord_token_dependency),
):
    """Get user's Discord guilds (servers)."""
    try:
        guilds = await discord_service.get_user_guilds(discord_token)
        return {"guilds": guilds}
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Discord guilds fetch failed: %s", error)
        raise_integration_http_error(error, fallback_detail="Failed to get guilds")
    except Exception as e:
        logger.error("Failed to get Discord guilds: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get guilds",
        )


@router.post("/discord/send-message")
async def send_discord_message(
    channel_id: str = Query(..., description="Channel ID"),
    content: str = Query(..., description="Message content"),
    tts: bool = Query(False, description="Use text-to-speech"),
    discord_token: str = Depends(discord_token_dependency),
):
    """Send a message to a Discord channel."""
    try:
        message = await discord_service.send_message(discord_token, channel_id, content, tts)
        return message
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Discord send message failed: %s", error)
        raise_integration_http_error(error, fallback_detail="Failed to send message")
    except Exception as e:
        logger.error("Failed to send Discord message: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message",
        )


@router.get("/discord/channels/{guild_id}")
async def get_discord_channels(
    guild_id: str,
    discord_token: str = Depends(discord_token_dependency),
):
    """Get channels in a Discord guild."""
    try:
        channels = await discord_service.get_guild_channels(discord_token, guild_id)
        return {"channels": channels}
    except HTTPException:
        raise
    except IntegrationServiceError as error:
        logger.warning("Discord channels fetch failed: %s", error)
        raise_integration_http_error(error, fallback_detail="Failed to get channels")
    except Exception as e:
        logger.error("Failed to get Discord channels: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get channels",
        )
