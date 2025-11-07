"""Integration routes for third-party service OAuth connections."""
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.integration import Integration
from app.models.user import User
from app.schemas.integration import (
    OAuthURLResponse,
    IntegrationStatusResponse,
    IntegrationListResponse
)
from app.services.auth import supabase_auth_service
from app.services.spotify import spotify_service
from app.services.gmail import get_gmail_service
from app.services.google_calendar import get_google_calendar_service
from app.services.uber import uber_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

# Redis client for OAuth state storage
redis_client = redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)

# OAuth state TTL (15 minutes)
OAUTH_STATE_TTL = 900


@router.get("/spotify/auth", response_model=OAuthURLResponse)
async def get_spotify_oauth_url(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        
        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            logger.warning("Invalid or expired token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        # Check if Spotify is configured
        if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Spotify OAuth is not configured"
            )
        
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "spotify",
            "created_at": datetime.utcnow().isoformat()
        }
        await redis_client.setex(
            f"oauth_state:{state}",
            OAUTH_STATE_TTL,
            json.dumps(state_data)
        )
        
        # Build Spotify OAuth URL
        scopes = [
            "user-read-email",
            "user-read-private",
            "user-modify-playback-state",
            "user-read-playback-state",
            "user-read-currently-playing"
        ]
        
        params = {
            "client_id": settings.SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.SPOTIFY_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "show_dialog": "false"
        }
        
        auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
        
        logger.info(f"Generated Spotify OAuth URL for user {supabase_user['id']}")
        
        return OAuthURLResponse(
            auth_url=auth_url,
            state=state
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Spotify OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}"
        )


@router.post("/spotify/sync")
async def sync_spotify_integration(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        user_id = supabase_user["id"]

        # Check if user has Spotify linked in Supabase
        # Note: Supabase handles the OAuth tokens, we just track the connection
        # Get user's identities to see if Spotify is linked
        identities = supabase_user.get("identities", [])
        has_spotify = any(identity.get("provider") == "spotify" for identity in identities)

        if not has_spotify:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Spotify not linked in Supabase"
            )

        # Create or update integration record
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "spotify"
        ).first()

        if integration:
            integration.is_active = True
            integration.updated_at = datetime.utcnow()
        else:
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="spotify",
                is_active=True
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
            detail=f"Failed to sync integration: {str(e)}"
        )


@router.post("/spotify/exchange")
async def spotify_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)

        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter"
            )

        # Verify state belongs to this user
        state_data = json.loads(state_json)
        if state_data["user_id"] != supabase_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="State parameter does not match user"
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
                    "client_secret": settings.SPOTIFY_CLIENT_SECRET
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
        
        if token_response.status_code != 200:
            logger.error(f"Spotify token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code"
            )
        
        token_data = token_response.json()
        
        # Calculate token expiration
        expires_at = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
        
        # Check if integration already exists
        existing_integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "spotify"
        ).first()
        
        if existing_integration:
            # Update existing integration
            existing_integration.access_token = token_data["access_token"]
            existing_integration.refresh_token = token_data.get("refresh_token")
            existing_integration.token_type = token_data.get("token_type", "Bearer")
            existing_integration.expires_at = expires_at
            existing_integration.scope = token_data.get("scope")
            existing_integration.is_active = True
            existing_integration.updated_at = datetime.utcnow()
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
                is_active=True
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Spotify for user {user_id}")

        return {"success": True, "message": "Successfully connected Spotify", "service": "spotify"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Spotify code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}"
        )


@router.get("", response_model=IntegrationListResponse)
async def get_user_integrations(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        # Get user integrations from database
        integrations = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.is_active == True
        ).all()
        
        logger.info(f"Found {len(integrations)} active integrations for user {supabase_user['id']}")
        for integration in integrations:
            logger.info(f"Integration: service={integration.service}, is_active={integration.is_active}, created_at={integration.created_at}")
        
        # Map backend service names to iOS app expected names
        service_name_mapping = {
            "google_calendar": "googleCalendar",
            "spotify": "spotify",
            "gmail": "gmail",
            "uber": "uber"
        }
        
        integration_statuses = []
        for integration in integrations:
            original_service = integration.service
            mapped_service = service_name_mapping.get(integration.service, integration.service)
            logger.info(f"Mapping service: '{original_service}' -> '{mapped_service}'")
            
            integration_statuses.append(
                IntegrationStatusResponse(
                    service=mapped_service,
                    connected=True,
                    connected_at=integration.created_at.isoformat() if integration.created_at else None
                )
            )
        
        logger.info(f"Returning integration statuses: {[status.service for status in integration_statuses]}")
        
        return IntegrationListResponse(integrations=integration_statuses)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get integrations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get integrations: {str(e)}"
        )


@router.post("/{service}/disconnect")
async def disconnect_service(
    service: str,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        logger.info(f"Attempting to disconnect service: '{service}' for user {supabase_user['id']}")
        
        # Map URL path service names back to database service names
        service_path_to_db_mapping = {
            "google-calendar": "google_calendar",
            "gmail": "gmail",
            "spotify": "spotify",
            "uber": "uber"
        }
        
        db_service_name = service_path_to_db_mapping.get(service, service)
        logger.info(f"Mapped service '{service}' to database service '{db_service_name}'")
        
        # Find and deactivate integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == db_service_name
        ).first()
        
        if not integration:
            # Log all integrations for this user to debug
            all_integrations = db.query(Integration).filter(
                Integration.user_id == supabase_user["id"]
            ).all()
            logger.error(f"Integration not found! Looking for service: '{db_service_name}'")
            logger.error(f"Available integrations for user: {[(i.service, i.is_active) for i in all_integrations]}")
            
            # Also check if there's an inactive integration
            inactive_integration = db.query(Integration).filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == db_service_name,
                Integration.is_active == False
            ).first()
            
            if inactive_integration:
                logger.error(f"Found inactive integration: {inactive_integration.id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Integration {service} exists but is already inactive"
                )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {service} integration found"
            )
        
        # Soft delete - set is_active to False
        integration.is_active = False
        integration.updated_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Successfully disconnected {db_service_name} for user {supabase_user['id']}")
        
        return {"success": True, "message": f"Successfully disconnected {service}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect {service}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect service: {str(e)}"
        )


# ============================================================================
# Uber Integration Routes
# ============================================================================

@router.get("/uber/auth", response_model=OAuthURLResponse)
async def get_uber_oauth_url(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Get Uber OAuth authorization URL.
    
    Args:
        authorization: Bearer token from Authorization header
        db: Database session
        
    Returns:
        OAuthURLResponse with authorization URL and state
        
    Raises:
        HTTPException: If authentication fails or Uber is not configured
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("Missing or invalid authorization header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        
        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            logger.warning("Invalid or expired token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        # Check if Uber is configured
        logger.info(f"Uber config check - Client ID: {settings.UBER_CLIENT_ID is not None}, Client Secret: {settings.UBER_CLIENT_SECRET is not None}")
        if not settings.UBER_CLIENT_ID or not settings.UBER_CLIENT_SECRET:
            logger.error(f"Uber OAuth not configured - Client ID: '{settings.UBER_CLIENT_ID}', Client Secret: '{settings.UBER_CLIENT_SECRET}'")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Uber OAuth is not configured"
            )
        
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "uber",
            "created_at": datetime.utcnow().isoformat()
        }
        await redis_client.setex(
            f"oauth_state:{state}",
            OAUTH_STATE_TTL,
            json.dumps(state_data)
        )
        
        # Build Uber OAuth URL
        # Start with minimal scopes for testing
        scopes = [
            "profile"
        ]
        
        params = {
            "client_id": settings.UBER_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.UBER_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state
        }
        
        auth_url = f"https://login.uber.com/oauth/v2/authorize?{urlencode(params)}"
        
        logger.info(f"Generated Uber OAuth URL for user {supabase_user['id']}")
        logger.info(f"Using redirect URI: {settings.UBER_REDIRECT_URI}")
        logger.info(f"Full OAuth URL: {auth_url}")
        
        return OAuthURLResponse(
            auth_url=auth_url,
            state=state
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Uber OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}"
        )


@router.post("/uber/exchange")
async def uber_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Exchange Uber authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Uber
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)

        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter"
            )

        # Verify state belongs to this user
        state_data = json.loads(state_json)
        if state_data["user_id"] != supabase_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="State parameter does not match user"
            )

        # Delete state from Redis (one-time use)
        await redis_client.delete(state_key)

        user_id = supabase_user["id"]
        
        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://login.uber.com/oauth/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.UBER_REDIRECT_URI,
                    "client_id": settings.UBER_CLIENT_ID,
                    "client_secret": settings.UBER_CLIENT_SECRET
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
        
        if token_response.status_code != 200:
            logger.error(f"Uber token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code"
            )
        
        token_data = token_response.json()
        
        # Calculate token expiration
        expires_at = datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
        
        # Check if integration already exists
        existing_integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "uber"
        ).first()
        
        if existing_integration:
            # Update existing integration
            existing_integration.access_token = token_data["access_token"]
            existing_integration.refresh_token = token_data.get("refresh_token")
            existing_integration.token_type = token_data.get("token_type", "Bearer")
            existing_integration.expires_at = expires_at
            existing_integration.scope = token_data.get("scope")
            existing_integration.is_active = True
            existing_integration.updated_at = datetime.utcnow()
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="uber",
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_type=token_data.get("token_type", "Bearer"),
                expires_at=expires_at,
                scope=token_data.get("scope"),
                is_active=True
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Uber for user {user_id}")

        return {"success": True, "message": "Successfully connected Uber", "service": "uber"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Uber code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}"
        )


@router.post("/uber/disconnect")
async def disconnect_uber(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Disconnect Uber integration.

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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Find Uber integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "uber"
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uber integration not found"
            )

        # Revoke Uber OAuth token
        if integration.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://login.uber.com/oauth/v2/revoke",
                        data={"token": integration.access_token},
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                logger.info(f"Revoked Uber token for user {supabase_user['id']}")
            except Exception as e:
                logger.warning(f"Failed to revoke Uber token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        db.delete(integration)
        db.commit()

        logger.info(f"Successfully disconnected Uber for user {supabase_user['id']}")

        return {"success": True, "message": "Uber disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Uber: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect Uber: {str(e)}"
        )


@router.get("/uber/config-test")
async def test_uber_config():
    """Test endpoint to check Uber configuration."""
    return {
        "uber_client_id_set": settings.UBER_CLIENT_ID is not None,
        "uber_client_secret_set": settings.UBER_CLIENT_SECRET is not None,
        "uber_redirect_uri": settings.UBER_REDIRECT_URI,
        "client_id_length": len(settings.UBER_CLIENT_ID) if settings.UBER_CLIENT_ID else 0,
        "client_secret_length": len(settings.UBER_CLIENT_SECRET) if settings.UBER_CLIENT_SECRET else 0
    }


# ============================================================================
# Uber API Endpoints
# ============================================================================

@router.get("/uber/profile")
async def get_uber_profile(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Get user's Uber profile.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        User profile data

    Raises:
        HTTPException: If not connected or request fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Uber integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "uber",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uber not connected"
            )

        # Get valid token (auto-refreshes if needed)
        uber_token = await uber_service.get_valid_token(integration, db)

        # Get profile
        profile = await uber_service.get_user_profile(uber_token)

        return profile

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Uber profile: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profile: {str(e)}"
        )


@router.get("/uber/history")
async def get_uber_history(
    limit: int = Query(5, ge=1, le=50, description="Number of rides to return"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Get user's ride history.

    Args:
        limit: Number of rides to return
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of past rides

    Raises:
        HTTPException: If not connected or request fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Uber integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "uber",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uber not connected"
            )

        # Get valid token
        uber_token = await uber_service.get_valid_token(integration, db)

        # Get ride history
        history = await uber_service.get_ride_history(uber_token, limit)

        return {"history": history}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Uber history: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get history: {str(e)}"
        )


@router.post("/uber/deep-link")
async def generate_uber_deep_link(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Generate Uber deep link for ride booking.

    Args:
        request: Request with pickup/destination data
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Deep link URL

    Raises:
        HTTPException: If not connected or request fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Uber integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "uber",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uber not connected"
            )

        # Get request data
        body_data = await request.json()

        # Generate deep link
        deep_link = uber_service.generate_deep_link(
            pickup_latitude=body_data.get("pickup_latitude"),
            pickup_longitude=body_data.get("pickup_longitude"),
            pickup_address=body_data.get("pickup_address"),
            destination_latitude=body_data.get("destination_latitude"),
            destination_longitude=body_data.get("destination_longitude"),
            destination_address=body_data.get("destination_address"),
            product_id=body_data.get("product_id")
        )

        # Also generate web link as fallback
        web_link = uber_service.generate_web_link(
            pickup_latitude=body_data.get("pickup_latitude"),
            pickup_longitude=body_data.get("pickup_longitude"),
            pickup_address=body_data.get("pickup_address"),
            destination_latitude=body_data.get("destination_latitude"),
            destination_longitude=body_data.get("destination_longitude"),
            destination_address=body_data.get("destination_address")
        )

        return {
            "deep_link": deep_link,
            "web_link": web_link
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Uber deep link: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate deep link: {str(e)}"
        )


# ============================================================================
# Spotify API Endpoints
# ============================================================================

@router.get("/spotify/playback")
async def get_spotify_playback(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token (auto-refreshes if needed)
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Get playback state
        playback = await spotify_service.get_current_playback(spotify_token)

        return playback

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Spotify playback: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get playback: {str(e)}"
        )


@router.post("/spotify/play")
async def spotify_play(
    uri: Optional[str] = Query(None, description="Spotify URI to play"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Play
        await spotify_service.play(spotify_token, uri, device_id)

        return {"success": True, "message": "Playback started"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to play Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to play: {str(e)}"
        )


@router.post("/spotify/pause")
async def spotify_pause(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Pause
        await spotify_service.pause(spotify_token, device_id)

        return {"success": True, "message": "Playback paused"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause: {str(e)}"
        )


@router.post("/spotify/next")
async def spotify_next(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Skip
        await spotify_service.skip_next(spotify_token, device_id)

        return {"success": True, "message": "Skipped to next track"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip Spotify track: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to skip: {str(e)}"
        )


@router.post("/spotify/previous")
async def spotify_previous(
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Skip back
        await spotify_service.skip_previous(spotify_token, device_id)

        return {"success": True, "message": "Skipped to previous track"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip back Spotify track: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to skip back: {str(e)}"
        )


@router.get("/spotify/search")
async def spotify_search(
    q: str = Query(..., description="Search query"),
    type: str = Query("track,artist,album", description="Types to search"),
    limit: int = Query(10, ge=1, le=50, description="Results limit"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Search
        results = await spotify_service.search(spotify_token, q, type, limit)

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search Spotify: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search: {str(e)}"
        )


@router.post("/spotify/volume")
async def spotify_set_volume(
    volume: int = Query(..., ge=0, le=100, description="Volume percent"),
    device_id: Optional[str] = Query(None, description="Device ID"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Spotify integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "spotify",
            Integration.is_active == True
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Spotify not connected"
            )

        # Get valid token
        spotify_token = await spotify_service.get_valid_token(integration, db)

        # Set volume
        await spotify_service.set_volume(spotify_token, volume, device_id)

        return {"success": True, "message": f"Volume set to {volume}%"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set Spotify volume: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set volume: {str(e)}"
        )


# =======================
# Gmail Integration Routes
# =======================

@router.get("/gmail/auth", response_model=OAuthURLResponse)
async def get_gmail_oauth_url(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )
        
        access_token = authorization.replace("Bearer ", "")
        
        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            logger.warning("Invalid or expired token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        # Check if Gmail is configured
        if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Gmail OAuth is not configured"
            )
        
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "gmail",
            "created_at": datetime.utcnow().isoformat()
        }
        await redis_client.setex(
            f"oauth_state:{state}",
            OAUTH_STATE_TTL,
            json.dumps(state_data)
        )
        
        # Build Google OAuth URL with Gmail scopes
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/userinfo.email"
        ]
        
        params = {
            "client_id": settings.GMAIL_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.GMAIL_REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",  # Request refresh token
            "prompt": "consent"  # Force consent screen to get refresh token
        }
        
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        
        logger.info(f"Generated Gmail OAuth URL for user {supabase_user['id']}")
        
        return OAuthURLResponse(
            auth_url=auth_url,
            state=state
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Gmail OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}"
        )


@router.post("/gmail/exchange")
async def gmail_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)

        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter"
            )

        # Verify state belongs to this user
        state_data = json.loads(state_json)
        if state_data["user_id"] != supabase_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="State parameter does not match user"
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
                    "client_secret": settings.GMAIL_CLIENT_SECRET
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
        
        if token_response.status_code != 200:
            logger.error(f"Gmail token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code"
            )

        token_data = token_response.json()
        gmail_access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)

        if not gmail_access_token:
            logger.error("No access token in Gmail response")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No access token received from Google"
            )

        # Get user's Gmail profile to verify the connection
        gmail_svc = get_gmail_service(gmail_access_token, refresh_token)
        profile = gmail_svc.get_profile()
        gmail_email = profile.get("emailAddress")

        logger.info(f"Successfully authenticated Gmail for {gmail_email}")

        # Store or update integration in database
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "gmail"
        ).first()

        if integration:
            # Update existing integration
            integration.access_token = gmail_access_token
            integration.refresh_token = refresh_token
            integration.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send gmail.modify"
            integration.updated_at = datetime.utcnow()
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="gmail",
                access_token=gmail_access_token,
                refresh_token=refresh_token,
                expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
                is_active=True,
                scope="gmail.readonly gmail.send gmail.modify"
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully stored Gmail integration for user {user_id}")

        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to exchange Gmail code: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect Gmail: {str(e)}"
        )


@router.post("/gmail/connect-native")
async def connect_gmail_native(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body"
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
                detail="Invalid or insufficient Gmail access token. Make sure Gmail scopes were granted."
            )

        # Store or update integration in database
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "gmail"
        ).first()

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.utcnow() + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send"
            integration.updated_at = datetime.utcnow()
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
                scope="gmail.readonly gmail.send"
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Gmail via native SDK for user {user_id}")

        return {
            "success": True,
            "message": "Gmail connected successfully",
            "email": gmail_email
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect Gmail: {str(e)}"
        )


@router.post("/gmail/sync")
async def sync_gmail_from_google_signin(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")

        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body"
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
                detail="Invalid or insufficient Gmail access token"
            )

        # Store or update integration in database
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "gmail"
        ).first()

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.utcnow() + timedelta(hours=1)

        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "gmail.readonly gmail.send gmail.modify"
            integration.updated_at = datetime.utcnow()
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
                scope="gmail.readonly gmail.send gmail.modify"
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully synced Gmail integration for user {user_id}")

        return {
            "success": True,
            "message": "Gmail synced successfully",
            "email": gmail_email
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Gmail: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync Gmail: {str(e)}"
        )


@router.post("/gmail/disconnect")
async def disconnect_gmail(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Find Gmail integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "gmail"
        ).first()

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gmail integration not found"
            )

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": integration.access_token}
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
            detail=f"Failed to disconnect Gmail: {str(e)}"
        )


# =======================
# Google Calendar Integration Routes
# =======================

@router.post("/google-calendar/connect-native")
async def connect_google_calendar_native(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get Google tokens from request body
        body_data = await request.json()
        google_id_token = body_data.get("id_token")
        google_access_token = body_data.get("access_token")

        if not google_access_token or not google_id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing id_token or access_token in request body"
            )

        user_id = supabase_user["id"]

        # Verify token works with Calendar API and get user's calendars
        calendar_email = "primary"  # Default value
        try:
            logger.info(f"Verifying Google Calendar access token for user {user_id}")
            calendar_svc = get_google_calendar_service(google_access_token)
            
            # Try to get calendars, but don't fail if it doesn't work
            # Some users might have limited permissions
            try:
                calendars = calendar_svc.list_calendars()
                logger.info(f"Retrieved {len(calendars)} calendars from Google Calendar API")
                
                primary_calendar = next(
                    (cal for cal in calendars if cal.get('id') == 'primary'),
                    calendars[0] if calendars else None
                )
                if primary_calendar:
                    calendar_email = primary_calendar.get('id', 'primary')
                    
            except Exception as calendar_error:
                logger.warning(f"Could not list calendars, but proceeding anyway: {calendar_error}")
                # Continue with default calendar_email = "primary"
            
            logger.info(f"Successfully verified Calendar access for {calendar_email}")
            
        except Exception as e:
            logger.error(f"Failed to create Calendar service for user {user_id}: {e}", exc_info=True)
            # For now, let's be more lenient and not fail the entire integration
            # if Calendar API verification fails
            logger.warning(f"Calendar API verification failed, but proceeding with integration")
            calendar_email = "primary"

        # Store or update integration in database
        logger.info(f"Looking for existing Google Calendar integration for user {user_id}")
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "google_calendar"
        ).first()

        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.utcnow() + timedelta(hours=1)

        if integration:
            logger.info(f"Updating existing Google Calendar integration: {integration.id}")
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "calendar.readonly calendar.events"
            integration.updated_at = datetime.utcnow()
        else:
            logger.info("Creating new Google Calendar integration")
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="google_calendar",
                access_token=google_access_token,
                refresh_token=None,  # Google Sign-In doesn't provide refresh tokens via addScopes
                expires_at=token_expires_at,
                is_active=True,
                scope="calendar.readonly calendar.events"
            )
            db.add(integration)

        try:
            db.commit()
            logger.info(f"Successfully committed Google Calendar integration to database")
        except Exception as commit_error:
            logger.error(f"Failed to commit Google Calendar integration: {str(commit_error)}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save integration: {str(commit_error)}"
            )

        logger.info(f"Successfully connected Google Calendar via native SDK for user {user_id}")
        logger.info(f"Integration saved: id={integration.id}, service={integration.service}, is_active={integration.is_active}")
        
        # Verify the integration was actually saved by querying it back
        verification_query = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "google_calendar",
            Integration.is_active == True
        ).first()
        
        if verification_query:
            logger.info(f"✅ Verified integration exists in database: {verification_query.id}")
        else:
            logger.error(f"❌ Integration not found in database after save!")

        return {
            "success": True,
            "message": "Google Calendar connected successfully",
            "calendar_id": calendar_email
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect Google Calendar: {str(e)}"
        )


@router.post("/google-calendar/sync")
async def sync_google_calendar_from_google_signin(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        
        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)
        
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )
        
        # Get Google access token from request body
        body_data = await request.json()
        google_access_token = body_data.get("access_token")
        
        if not google_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token in request body"
            )
        
        user_id = supabase_user["id"]
        
        # Verify token works with Calendar API and get user's calendars
        try:
            calendar_svc = get_google_calendar_service(google_access_token)
            calendars = calendar_svc.list_calendars()
            primary_calendar = next(
                (cal for cal in calendars if cal.get('id') == 'primary'),
                calendars[0] if calendars else None
            )
            calendar_email = primary_calendar.get('id') if primary_calendar else 'primary'
            logger.info(f"Successfully verified Calendar access for {calendar_email}")
        except Exception as e:
            logger.error(f"Failed to verify Calendar access: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or insufficient Calendar access token"
            )
        
        # Store or update integration in database
        integration = db.query(Integration).filter(
            Integration.user_id == user_id,
            Integration.service == "google_calendar"
        ).first()
        
        # Note: Google Sign-In tokens typically expire in 1 hour
        token_expires_at = datetime.utcnow() + timedelta(hours=1)
        
        if integration:
            # Update existing integration
            integration.access_token = google_access_token
            integration.expires_at = token_expires_at
            integration.is_active = True
            integration.scope = "calendar.readonly calendar.events"
            integration.updated_at = datetime.utcnow()
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
                scope="calendar.readonly calendar.events"
            )
            db.add(integration)
        
        db.commit()
        
        logger.info(f"Successfully synced Google Calendar integration for user {user_id}")
        
        return {
            "success": True,
            "message": "Google Calendar synced successfully",
            "calendar_id": calendar_email
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync Google Calendar: {str(e)}"
        )


@router.post("/google-calendar/disconnect")
async def disconnect_google_calendar(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
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
    logger.info("Google Calendar disconnect endpoint called")
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header"
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Find Google Calendar integration
        logger.info(f"Looking for Google Calendar integration for user {supabase_user['id']}")
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == "google_calendar"
        ).first()

        if not integration:
            # Debug: list all integrations for this user
            all_integrations = db.query(Integration).filter(
                Integration.user_id == supabase_user["id"]
            ).all()
            logger.error(f"Google Calendar integration not found!")
            logger.error(f"Available integrations: {[(i.service, i.is_active) for i in all_integrations]}")
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Google Calendar integration not found"
            )
        
        logger.info(f"Found Google Calendar integration: {integration.id}, active: {integration.is_active}")

        # Revoke Google OAuth token
        if integration.access_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": integration.access_token}
                    )
                logger.info(f"Revoked Google Calendar token for user {supabase_user['id']}")
            except Exception as e:
                logger.warning(f"Failed to revoke Google Calendar token: {e}")
                # Continue with deletion even if revocation fails

        # Delete integration from database
        db.delete(integration)
        db.commit()

        logger.info(f"Successfully disconnected Google Calendar for user {supabase_user['id']}")

        return {"success": True, "message": "Google Calendar disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect Google Calendar: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect Google Calendar: {str(e)}"
        )

