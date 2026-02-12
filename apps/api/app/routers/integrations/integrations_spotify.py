"""Spotify integration routes."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.integration import Integration
from app.schemas.integration import OAuthURLResponse, SpotifySyncRequest
from app.services.integrations.spotify import spotify_client
from app.services.user.auth import supabase_auth_service

from .integrations_shared import OAUTH_STATE_TTL, redis_client

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/spotify/auth", response_model=OAuthURLResponse)
async def get_spotify_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Spotify OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Spotify is not configured
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

        # Check if Spotify is configured
        if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Spotify OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "spotify",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
        )

        # Build Spotify OAuth URL
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

        logger.info(f"Generated Spotify OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Spotify OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.post("/spotify/sync")
async def sync_spotify_integration(
    request: SpotifySyncRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Sync Spotify integration from client-provided tokens.

    Called by iOS app after successful Supabase Spotify OAuth (or native auth).

    Args:
        request: Request body containing tokens
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If sync fails
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

        user_id = supabase_user["id"]

        # Calculate expiration
        expires_at = None
        if request.expires_in:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in)
        else:
            # Default to 1 hour if not provided
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Create or update integration record
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "spotify")
            .first()
        )

        if integration:
            integration.access_token = request.access_token
            if request.refresh_token:
                integration.refresh_token = request.refresh_token
            integration.expires_at = expires_at
            integration.is_active = True
            integration.updated_at = datetime.now(timezone.utc)
        else:
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="spotify",
                access_token=request.access_token,
                refresh_token=request.refresh_token,
                expires_at=expires_at,
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully synced Spotify integration for user {user_id}")

        return {"success": True, "message": "Spotify integration synced"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Spotify integration: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync integration: {str(e)}",
        )


@router.post("/spotify/exchange")
async def spotify_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Spotify authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Spotify
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
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
                    "client_id": settings.SPOTIFY_CLIENT_ID,
                    "client_secret": settings.SPOTIFY_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Spotify token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()

        # Calculate token expiration
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data.get("expires_in", 3600)
        )

        # Check if integration already exists
        existing_integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "spotify")
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
                service="spotify",
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_type=token_data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scope=token_data.get("scope"),
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Spotify for user {user_id}")

        return {
            "success": True,
            "message": "Successfully connected Spotify",
            "service": "spotify",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Spotify code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}",
        )


# ============================================================================
# Spotify API Endpoints
# ============================================================================


@router.get("/spotify/playback")
async def get_spotify_playback(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get current Spotify playback state.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Current playback state

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token (auto-refreshes if needed)
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Get playback state
        playback = await spotify_client.get_current_playback(spotify_token)

        return playback

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Spotify playback: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get playback: {str(e)}",
        )


@router.post("/spotify/play")
async def spotify_play(
    uri: Optional[str] = Query(None, description="Spotify URI to play"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Start or resume Spotify playback.

    Args:
        uri: Optional Spotify URI (track, album, playlist, etc.)
        device_id: Optional device ID to play on
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Play
        await spotify_client.play(spotify_token, uri, device_id)

        return {"success": True, "message": "Playback started"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to play Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to play: {str(e)}",
        )


@router.post("/spotify/pause")
async def spotify_pause(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Pause Spotify playback.

    Args:
        device_id: Optional device ID to pause on
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Pause
        await spotify_client.pause(spotify_token, device_id)

        return {"success": True, "message": "Playback paused"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause: {str(e)}",
        )


@router.post("/spotify/next")
async def spotify_next(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Skip to next track.

    Args:
        device_id: Optional device ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Skip
        await spotify_client.skip_next(spotify_token, device_id)

        return {"success": True, "message": "Skipped to next track"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip Spotify track: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to skip: {str(e)}",
        )


@router.post("/spotify/previous")
async def spotify_previous(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Skip to previous track.

    Args:
        device_id: Optional device ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Skip back
        await spotify_client.skip_previous(spotify_token, device_id)

        return {"success": True, "message": "Skipped to previous track"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip back Spotify track: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to skip back: {str(e)}",
        )


@router.get("/spotify/search")
async def spotify_search(
    q: str = Query(..., description="Search query"),
    type: str = Query("track,artist,album", description="Types to search"),
    limit: int = Query(10, ge=1, le=50, description="Results limit"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Search Spotify catalog.

    Args:
        q: Search query
        type: Comma-separated list of types (track, artist, album, playlist)
        limit: Number of results per type (1-50)
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Search results

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Search
        results = await spotify_client.search(spotify_token, q, type, limit)

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search: {str(e)}",
        )


@router.post("/spotify/volume")
async def spotify_set_volume(
    volume: int = Query(..., ge=0, le=100, description="Volume percent"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Set Spotify playback volume.

    Args:
        volume: Volume level (0-100)
        device_id: Optional device ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not connected or request fails
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

        # Get Spotify integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "spotify",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_client.get_valid_token(integration, db)

        # Set volume
        await spotify_client.set_volume(spotify_token, volume, device_id)

        return {"success": True, "message": f"Volume set to {volume}%"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set Spotify volume: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set volume: {str(e)}",
        )
