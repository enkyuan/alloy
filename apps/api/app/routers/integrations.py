"""Integration routes for third-party service OAuth connections."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, cast
from urllib.parse import urlencode

import httpx
import redis.asyncio as redis
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.integration import Integration
from app.models.user import User
from app.schemas.integration import (
    IntegrationListResponse,
    IntegrationStatusResponse,
    OAuthURLResponse,
)
from app.services.spotify import spotify_client, spotify_service
from app.services.user.auth import supabase_auth_service
from app.services.workspace.gcalendar import get_google_calendar_service
from app.services.workspace.gmail import get_gmail_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

# Redis client for OAuth state storage
redis_client = redis.from_url(
    settings.REDIS_URL, encoding="utf-8", decode_responses=True
)

# OAuth state TTL (15 minutes)
OAUTH_STATE_TTL = 900


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
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Sync Spotify integration from Supabase to our database.

    Called by iOS app after successful Supabase Spotify OAuth.

    Args:
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

        # Check if user has Spotify linked in Supabase
        # Note: Supabase handles the OAuth tokens, we just track the connection
        # Get user's identities to see if Spotify is linked
        identities = supabase_user.get("identities", [])
        has_spotify = any(
            identity.get("provider") == "spotify" for identity in identities
        )

        if not has_spotify:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Spotify not linked in Supabase",
            )

        # Create or update integration record
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "spotify")
            .first()
        )

        if integration:
            integration.is_active = True
            integration.updated_at = datetime.now(timezone.utc)
        else:
            integration = Integration(
                id=str(uuid.uuid4()), user_id=user_id, service="spotify", is_active=True
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


# =======================
# Gmail Integration Routes
# =======================


@router.get("/gmail/auth", response_model=OAuthURLResponse)
async def get_gmail_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Gmail OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Gmail is not configured
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

        # Check if Gmail is configured
        if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gmail OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "gmail",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
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
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.post("/gmail/exchange")
async def gmail_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Gmail authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Google
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
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.GMAIL_REDIRECT_URI,
                    "client_id": settings.GMAIL_CLIENT_ID,
                    "client_secret": settings.GMAIL_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Gmail token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()
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

        # Store or update integration in database
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "gmail")
            .first()
        )

        if integration:
            # Update existing integration
            integration.access_token = gmail_access_token
            integration.refresh_token = refresh_token
            integration.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in
            )
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send gmail.modify"
            integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="gmail",
                access_token=gmail_access_token,
                refresh_token=refresh_token,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                is_active=True,
                scope="gmail.readonly gmail.send gmail.modify",
            )
            db.add(integration)

        db.commit()

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
            detail=f"Failed to connect Gmail: {str(e)}",
        )


@router.post("/gmail/connect-native")
async def connect_gmail_native(
    request: Request, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Connect Gmail using native Google Sign-In SDK (iOS).

    This endpoint receives ID token and access token from Google Sign-In SDK
    and stores them for Gmail API access. This bypasses the loopback flow
    that Google has deprecated.

    Args:
        request: FastAPI request object with id_token and access_token
        authorization: Bearer token (Supabase) from Authorization header
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If connection fails
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

        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body",
            )

        user_id = supabase_user["id"]

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

        # Store or update integration in database
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "gmail")
            .first()
        )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send"
            integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="gmail",
                access_token=google_access_token,
                refresh_token=None,  # Google Sign-In doesn't provide refresh tokens via addScopes
                expires_at=token_expires_at,
                is_active=True,
                scope="gmail.readonly gmail.send",
            )
            db.add(integration)

        db.commit()

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
            detail=f"Failed to connect Gmail: {str(e)}",
        )


@router.post("/gmail/sync")
async def sync_gmail_from_google_signin(
    request: Request, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Sync Gmail integration from Google Sign-In access token (legacy).

    This endpoint is called automatically when a user signs in with Google
    and has granted Gmail scopes. The iOS app sends the Google OAuth access
    token, and we store it for Gmail API access.

    Note: This is deprecated in favor of /gmail/connect-native which uses
    the native Google Sign-In SDK flow.

    Args:
        request: FastAPI request object
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response with integration status

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

        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body",
            )

        user_id = supabase_user["id"]

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

        # Store or update integration in database
        integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "gmail")
            .first()
        )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send gmail.modify"
            integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="gmail",
                access_token=google_access_token,
                refresh_token=None,  # Google Sign-In doesn't provide refresh tokens
                expires_at=token_expires_at,
                is_active=True,
                scope="gmail.readonly gmail.send gmail.modify",
            )
            db.add(integration)

        db.commit()

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
            detail=f"Failed to sync Gmail: {str(e)}",
        )


@router.post("/gmail/disconnect")
async def disconnect_gmail(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Disconnect Gmail integration.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If not authenticated or disconnection fails
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

        # Find Gmail integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "gmail",
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gmail integration not found",
            )

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": str(integration.access_token)},
                    )
                logger.info(f"Revoked Gmail token for user {supabase_user['id']}")
            except Exception as e:
                logger.warning(f"Failed to revoke Gmail token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        db.delete(integration)
        db.commit()

        logger.info(f"Successfully disconnected Gmail for user {supabase_user['id']}")

        return {"success": True, "message": "Gmail disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect Gmail: {str(e)}",
        )


# =======================
# Google Calendar Integration Routes
# =======================


@router.post("/google-calendar/connect-native")
async def connect_google_calendar_native(
    request: Request, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Connect Google Calendar using native Google Sign-In SDK (iOS).

    This endpoint receives ID token and access token from Google Sign-In SDK
    and stores them for Calendar API access. This bypasses the loopback flow
    that Google has deprecated.

    Args:
        request: FastAPI request object with id_token and access_token
        authorization: Bearer token (Supabase) from Authorization header
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If connection fails
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

        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body",
            )

        user_id = supabase_user["id"]

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

        # Store or update integration in database
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == user_id, Integration.service == "google_calendar"
            )
            .first()
        )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "calendar.readonly calendar.events"
            integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="google_calendar",
                access_token=google_access_token,
                refresh_token=None,  # Google Sign-In doesn't provide refresh tokens via addScopes
                expires_at=token_expires_at,
                is_active=True,
                scope="calendar.readonly calendar.events",
            )
            db.add(integration)

        db.commit()

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
            detail=f"Failed to connect Google Calendar: {str(e)}",
        )


@router.post("/google-calendar/sync")
async def sync_google_calendar_from_google_signin(
    request: Request, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Sync Google Calendar integration from Google Sign-In access token (legacy).

    This endpoint is called automatically when a user signs in with Google
    and has granted Calendar scopes. The iOS app sends the Google OAuth access
    token, and we store it for Calendar API access.

    Note: This is deprecated in favor of /google-calendar/connect-native which uses
    the native Google Sign-In SDK flow.

    Args:
        request: FastAPI request object
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response with integration status

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

        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body",
            )

        user_id = supabase_user["id"]

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

        # Store or update integration in database
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == user_id, Integration.service == "google_calendar"
            )
            .first()
        )

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "calendar.readonly calendar.events"
            integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="google_calendar",
                access_token=google_access_token,
                refresh_token=None,  # Google Sign-In doesn't provide refresh tokens
                expires_at=token_expires_at,
                is_active=True,
                scope="calendar.readonly calendar.events",
            )
            db.add(integration)

        db.commit()

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
            detail=f"Failed to sync Google Calendar: {str(e)}",
        )


@router.post("/google-calendar/disconnect")
async def disconnect_google_calendar(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Disconnect Google Calendar integration.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response

    Raises:
        HTTPException: If not authenticated or disconnection fails
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

        # Find Google Calendar integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "google_calendar",
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Google Calendar integration not found",
            )

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": str(integration.access_token)},
                    )
                logger.info(
                    f"Revoked Google Calendar token for user {supabase_user['id']}"
                )
            except Exception as e:
                logger.warning(f"Failed to revoke Google Calendar token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        db.delete(integration)
        db.commit()

        logger.info(
            f"Successfully disconnected Google Calendar for user {supabase_user['id']}"
        )

        return {"success": True, "message": "Google Calendar disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect Google Calendar: {str(e)}",
        )


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
        logger.info(f"Using redirect URI: {settings.DISCORD_REDIRECT_URI}")
        logger.info(f"Full OAuth URL: {auth_url}")

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
    logger.info(
        f"Discord OAuth callback received - code: {code[:20]}..., state: {state[:20]}..."
    )

    # Redirect to iOS app with code and state
    redirect_url = f"milo://discord/callback?code={code}&state={state}"
    logger.info(f"Redirecting to iOS app: {redirect_url}")

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


# ============================================================================
# Todoist Integration Routes
# ============================================================================


@router.get("/todoist/auth", response_model=OAuthURLResponse)
async def get_todoist_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Todoist OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Todoist is not configured
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

        # Check if Todoist is configured
        if not settings.TODOIST_CLIENT_ID or not settings.TODOIST_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Todoist OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "todoist",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
        )

        # Build Todoist OAuth URL
        scopes = ["data:read_write", "data:delete", "project:delete"]

        params = {
            "client_id": settings.TODOIST_CLIENT_ID,
            "scope": ",".join(scopes),
            "state": state,
        }

        auth_url = f"https://todoist.com/oauth/authorize?{urlencode(params)}"

        logger.info(f"Generated Todoist OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Todoist OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.get("/todoist/callback")
async def todoist_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Todoist OAuth callback and redirect to iOS app.

    This endpoint receives the OAuth callback from Todoist and redirects
    to the iOS app with the code and state parameters.

    Args:
        code: Authorization code from Todoist
        state: State parameter for CSRF protection

    Returns:
        Redirect to iOS app with code and state
    """
    # Redirect to iOS app with code and state
    redirect_url = f"milo://todoist/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/todoist/exchange")
async def todoist_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Todoist authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Todoist
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
                "https://todoist.com/oauth/access_token",
                data={
                    "client_id": settings.TODOIST_CLIENT_ID,
                    "client_secret": settings.TODOIST_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Todoist token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()

        # Todoist tokens don't expire, set far future date
        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)

        # Check if integration already exists
        existing_integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "todoist")
            .first()
        )

        if existing_integration:
            # Update existing integration
            existing_integration.access_token = token_data["access_token"]
            existing_integration.token_type = "Bearer"
            existing_integration.expires_at = expires_at
            existing_integration.is_active = True
            existing_integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="todoist",
                access_token=token_data["access_token"],
                token_type="Bearer",
                expires_at=expires_at,
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Todoist for user {user_id}")

        return {
            "success": True,
            "message": "Successfully connected Todoist",
            "service": "todoist",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Todoist code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}",
        )


# ============================================================================
# Todoist API Endpoints
# ============================================================================


@router.get("/todoist/tasks")
async def get_todoist_tasks(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    label: Optional[str] = Query(None, description="Filter by label"),
    filter_query: Optional[str] = Query(None, description="Todoist filter query"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Get Todoist tasks.

    Args:
        project_id: Filter by project ID
        label: Filter by label
        filter_query: Todoist filter query
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of tasks

    Raises:
        HTTPException: If not authenticated or Todoist not connected
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

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Get tasks
        tasks = await todoist_service.get_tasks(
            todoist_token, project_id=project_id, label=label, filter_query=filter_query
        )

        return {"tasks": tasks}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Todoist tasks: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tasks: {str(e)}",
        )


@router.post("/todoist/tasks")
async def create_todoist_task(
    content: str = Query(..., description="Task content"),
    description: Optional[str] = Query(None, description="Task description"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    due_string: Optional[str] = Query(None, description="Natural language due date"),
    priority: int = Query(1, ge=1, le=4, description="Priority (1-4)"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Create a Todoist task.

    Args:
        content: Task content/title
        description: Task description
        project_id: Project ID
        due_string: Natural language due date
        priority: Priority (1-4)
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Created task

    Raises:
        HTTPException: If not authenticated or Todoist not connected
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

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Create task
        task = await todoist_service.create_task(
            todoist_token,
            content=content,
            description=description,
            project_id=project_id,
            due_string=due_string,
            priority=priority,
        )

        return task

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create Todoist task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}",
        )


@router.post("/todoist/tasks/{task_id}/close")
async def close_todoist_task(
    task_id: str, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Complete a Todoist task.

    Args:
        task_id: Task ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not authenticated or Todoist not connected
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

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Close task
        await todoist_service.close_task(todoist_token, task_id)

        return {"success": True, "message": "Task completed"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close Todoist task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to close task: {str(e)}",
        )


@router.get("/todoist/projects")
async def get_todoist_projects(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Todoist projects.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of projects

    Raises:
        HTTPException: If not authenticated or Todoist not connected
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

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Get projects
        projects = await todoist_service.get_projects(todoist_token)

        return {"projects": projects}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Todoist projects: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get projects: {str(e)}",
        )


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
    redirect_url = f"milo://calendly/callback?code={code}&state={state}"
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
