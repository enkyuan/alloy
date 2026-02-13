"""Spotify integration routes."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse, SpotifySyncRequest
from app.services.integrations.spotify import spotify_client

from .integrations_shared import (
    exchange_oauth_code,
    persist_oauth_state,
    require_integration_token,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()


spotify_token_dependency = require_integration_token(
    "spotify",
    not_connected_detail="Spotify not connected",
    resolver=spotify_client.get_valid_token,
)


@router.get("/spotify/auth", response_model=OAuthURLResponse)
async def get_spotify_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Spotify OAuth authorization URL."""
    try:
        if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Spotify OAuth is not configured",
            )

        state = secrets.token_urlsafe(32)
        await persist_oauth_state(
            state=state, user_id=str(supabase_user["id"]), service="spotify"
        )

        scopes = [
            "user-read-email",
            "user-read-private",
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing",
        ]
        params = {
            "client_id": settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "show_dialog": "false",
        }
        auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"

        logger.info("Generated Spotify OAuth URL for user %s", supabase_user["id"])
        return OAuthURLResponse(authUrl=auth_url, state=state)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate Spotify OAuth URL: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        )


@router.post("/spotify/sync")
async def sync_spotify_integration(
    request: SpotifySyncRequest,
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Spotify integration from client-provided tokens."""
    try:
        user_id = str(supabase_user["id"])
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=request.expires_in or 3600
        )

        await upsert_integration(
            db=db,
            user_id=user_id,
            service="spotify",
            access_token=request.access_token,
            refresh_token=request.refresh_token,
            expires_at=expires_at,
            token_type="Bearer",
            overwrite_refresh_token=False,
        )

        logger.info("Successfully synced Spotify integration for user %s", user_id)
        return {"success": True, "message": "Spotify integration synced"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to sync Spotify integration: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync integration",
        )


@router.post("/spotify/exchange")
async def spotify_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Spotify authorization code for access token."""
    try:
        user_id = str(supabase_user["id"])
        await validate_and_consume_oauth_state(state=state, user_id=user_id)

        token_data = await exchange_oauth_code(
            token_url="https://accounts.spotify.com/api/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
                "client_id": settings.SPOTIFY_CLIENT_ID,
                "client_secret": settings.SPOTIFY_CLIENT_SECRET,
            },
        )

        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )
        await upsert_integration(
            db=db,
            user_id=user_id,
            service="spotify",
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            token_type=token_data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scope=token_data.get("scope"),
        )

        logger.info("Successfully connected Spotify for user %s", user_id)
        return {
            "success": True,
            "message": "Successfully connected Spotify",
            "service": "spotify",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Spotify code exchange failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to exchange code",
        )


# ============================================================================
# Spotify API Endpoints
# ============================================================================


@router.get("/spotify/playback")
async def get_spotify_playback(
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Get current Spotify playback state."""
    try:
        playback = await spotify_client.get_current_playback(spotify_token)
        return playback
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Spotify playback: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get playback",
        )


@router.post("/spotify/play")
async def spotify_play(
    uri: Optional[str] = Query(None, description="Spotify URI to play"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Start or resume Spotify playback."""
    try:
        await spotify_client.play(spotify_token, uri, device_id)
        return {"success": True, "message": "Playback started"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to play Spotify: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to play",
        )


@router.post("/spotify/pause")
async def spotify_pause(
    device_id: Optional[str] = Query(None, description="Device ID"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Pause Spotify playback."""
    try:
        await spotify_client.pause(spotify_token, device_id)
        return {"success": True, "message": "Playback paused"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to pause Spotify: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to pause",
        )


@router.post("/spotify/next")
async def spotify_next(
    device_id: Optional[str] = Query(None, description="Device ID"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Skip to next track."""
    try:
        await spotify_client.skip_next(spotify_token, device_id)
        return {"success": True, "message": "Skipped to next track"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to skip Spotify track: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip",
        )


@router.post("/spotify/previous")
async def spotify_previous(
    device_id: Optional[str] = Query(None, description="Device ID"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Skip to previous track."""
    try:
        await spotify_client.skip_previous(spotify_token, device_id)
        return {"success": True, "message": "Skipped to previous track"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to skip back Spotify track: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip back",
        )


@router.get("/spotify/search")
async def spotify_search(
    q: str = Query(..., description="Search query"),
    type: str = Query("track,artist,album", description="Types to search"),
    limit: int = Query(10, ge=1, le=50, description="Results limit"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Search Spotify catalog."""
    try:
        results = await spotify_client.search(spotify_token, q, type, limit)
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to search Spotify: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search",
        )


@router.post("/spotify/volume")
async def spotify_set_volume(
    volume: int = Query(..., ge=0, le=100, description="Volume percent"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    spotify_token: str = Depends(spotify_token_dependency),
):
    """Set Spotify playback volume."""
    try:
        await spotify_client.set_volume(spotify_token, volume, device_id)
        return {"success": True, "message": f"Volume set to {volume}%"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to set Spotify volume: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set volume",
        )
