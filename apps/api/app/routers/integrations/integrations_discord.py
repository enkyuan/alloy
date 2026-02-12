"""Discord integration routes."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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

# ============================================================================
# Discord Integration Routes
# ============================================================================


@router.get("/discord/auth", response_model=OAuthURLResponse)
async def get_discord_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Discord OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Discord is not configured
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

        # Check if Discord is configured
        if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Discord OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "discord",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
        )

        # Build Discord OAuth URL
        scopes = ["identify", "guilds", "guilds.members.read", "messages.read"]

        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.DISCORD_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
        }

        auth_url = f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"

        logger.info(f"Generated Discord OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Discord OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.get("/discord/callback")
async def discord_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Discord OAuth callback and redirect to iOS app.

    This endpoint receives the OAuth callback from Discord and redirects
    to the iOS app with the code and state parameters.

    Args:
        code: Authorization code from Discord
        state: State parameter for CSRF protection

    Returns:
        Redirect to iOS app with code and state
    """
    logger.info("Discord OAuth callback received")

    # Redirect to iOS app with code and state
    redirect_url = f"havenos://discord/callback?code={code}&state={state}"
    logger.debug("Redirecting Discord OAuth callback to iOS app")

    return RedirectResponse(url=redirect_url)


@router.post("/discord/exchange")
async def discord_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Discord authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Discord
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
                "https://discord.com/api/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.DISCORD_REDIRECT_URI,
                    "client_id": settings.DISCORD_CLIENT_ID,
                    "client_secret": settings.DISCORD_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Discord token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()

        # Calculate token expiration (Discord tokens last 7 days)
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 604800)
        )

        # Check if integration already exists
        existing_integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "discord")
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
                service="discord",
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_type=token_data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scope=token_data.get("scope"),
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Discord for user {user_id}")

        return {
            "success": True,
            "message": "Successfully connected Discord",
            "service": "discord",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Discord code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}",
        )


# ============================================================================
# Discord API Endpoints
# ============================================================================


@router.get("/discord/profile")
async def get_discord_profile(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Discord user profile.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Discord user profile

    Raises:
        HTTPException: If not authenticated or Discord not connected
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

        # Get Discord integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "discord",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Discord not connected"
            )

        # Import discord service
        from app.services.discord import discord_service

        # Get valid token (refresh if needed)
        discord_token = await discord_service.get_valid_token(integration, db)

        # Get user profile
        profile = await discord_service.get_current_user(discord_token)

        return profile

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Discord profile: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profile: {str(e)}",
        )


@router.get("/discord/guilds")
async def get_discord_guilds(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get user's Discord guilds (servers).

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of guilds

    Raises:
        HTTPException: If not authenticated or Discord not connected
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

        # Get Discord integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "discord",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Discord not connected"
            )

        # Import discord service
        from app.services.discord import discord_service

        # Get valid token (refresh if needed)
        discord_token = await discord_service.get_valid_token(integration, db)

        # Get guilds
        guilds = await discord_service.get_user_guilds(discord_token)

        return {"guilds": guilds}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Discord guilds: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get guilds: {str(e)}",
        )


@router.post("/discord/send-message")
async def send_discord_message(
    channel_id: str = Query(..., description="Channel ID"),
    content: str = Query(..., description="Message content"),
    tts: bool = Query(False, description="Use text-to-speech"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Send a message to a Discord channel.

    Args:
        channel_id: Discord channel ID
        content: Message content
        tts: Whether to use text-to-speech
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Created message

    Raises:
        HTTPException: If not authenticated or Discord not connected
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

        # Get Discord integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "discord",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Discord not connected"
            )

        # Import discord service
        from app.services.discord import discord_service

        # Get valid token (refresh if needed)
        discord_token = await discord_service.get_valid_token(integration, db)

        # Send message
        message = await discord_service.send_message(
            discord_token, channel_id, content, tts
        )

        return message

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send Discord message: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {str(e)}",
        )


@router.get("/discord/channels/{guild_id}")
async def get_discord_channels(
    guild_id: str, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get channels in a Discord guild.

    Args:
        guild_id: Discord guild ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of channels

    Raises:
        HTTPException: If not authenticated or Discord not connected
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

        # Get Discord integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "discord",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Discord not connected"
            )

        # Import discord service
        from app.services.discord import discord_service

        # Get valid token (refresh if needed)
        discord_token = await discord_service.get_valid_token(integration, db)

        # Get channels
        channels = await discord_service.get_guild_channels(discord_token, guild_id)

        return {"channels": channels}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Discord channels: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get channels: {str(e)}",
        )
