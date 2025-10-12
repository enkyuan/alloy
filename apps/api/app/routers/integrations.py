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
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query, Response
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


@router.get("/spotify/callback")
async def spotify_oauth_callback(
    code: Optional[str] = Query(None, description="OAuth authorization code"),
    state: Optional[str] = Query(None, description="OAuth state parameter"),
    error: Optional[str] = Query(None, description="OAuth error"),
    db: Session = Depends(get_db)
):
    """Handle Spotify OAuth callback.
    
    Args:
        code: Authorization code from Spotify
        state: State parameter for CSRF protection
        error: Error from Spotify (if authorization failed)
        db: Database session
        
    Returns:
        Redirect to modal:// URL scheme
        
    Raises:
        HTTPException: If callback processing fails
    """
    try:
        # Check for OAuth error
        if error:
            logger.warning(f"Spotify OAuth error: {error}")
            return RedirectResponse(url=f"modal://integrations?error={error}")
        
        if not code or not state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing code or state parameter"
            )
        
        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)
        
        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter"
            )
        
        # Delete state from Redis (one-time use)
        await redis_client.delete(state_key)
        
        state_data = json.loads(state_json)
        user_id = state_data["user_id"]
        
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
        
        # Redirect back to app with success=true
        return RedirectResponse(url="modal://integrations?success=true&service=spotify")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Spotify OAuth callback failed: {str(e)}", exc_info=True)
        return RedirectResponse(url=f"modal://integrations?error={str(e)}")


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
        
        integration_statuses = [
            IntegrationStatusResponse(
                service=integration.service,
                connected=True,
                connected_at=integration.created_at.isoformat() if integration.created_at else None
            )
            for integration in integrations
        ]
        
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
        
        # Find and deactivate integration
        integration = db.query(Integration).filter(
            Integration.user_id == supabase_user["id"],
            Integration.service == service
        ).first()
        
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active {service} integration found"
            )
        
        # Soft delete - set is_active to False
        integration.is_active = False
        integration.updated_at = datetime.utcnow()
        db.commit()
        
        logger.info(f"Successfully disconnected {service} for user {supabase_user['id']}")
        
        return {"success": True, "message": f"Successfully disconnected {service}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect {service}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect service: {str(e)}"
        )
