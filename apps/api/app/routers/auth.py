"""Authentication routes for OAuth and user management."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
)
from app.services.user.auth import supabase_auth_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


# Google OAuth removed - use Supabase Swift SDK directly in iOS app
# Authentication flow: iOS app -> Supabase SDK -> /auth/sync endpoint


# Apple OAuth removed - use Supabase Swift SDK directly in iOS app
# Authentication flow: iOS app -> Supabase SDK -> /auth/sync endpoint


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token.

    Args:
        request: Refresh token request
        db: Database session

    Returns:
        New TokenResponse with refreshed access token

    Raises:
        HTTPException: If refresh fails
    """
    try:
        # Refresh token with Supabase
        supabase_response = await supabase_auth_service.refresh_token(
            request.refresh_token
        )

        # Get user from database
        supabase_user = supabase_response.get("user")
        user = db.query(User).filter(User.id == supabase_user["id"]).first()

        if not user:
            logger.warning(f"User not found in database: {supabase_user['id']}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info(f"Successfully refreshed token for user: {user.email}")
        return TokenResponse(
            access_token=supabase_response["access_token"],
            token_type="bearer",
            expires_in=supabase_response.get("expires_in", 3600),
            refresh_token=supabase_response.get("refresh_token"),
            user=UserResponse.model_validate(user),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}",
        )


@router.post("/sync", response_model=UserResponse)
async def sync_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    """Sync user from Supabase to our database.

    Called by iOS app after successful Supabase authentication.
    This endpoint creates or updates the user in our local database.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        UserResponse with synced user data

    Raises:
        HTTPException: If authentication fails or sync error occurs
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

        # Get or create user in our database
        user = db.query(User).filter(User.id == supabase_user["id"]).first()

        if not user:
            # Create new user
            logger.info(f"Creating new user: {supabase_user['email']}")
            user = User(
                id=supabase_user["id"],
                email=supabase_user["email"],
                username=supabase_user.get("user_metadata", {}).get(
                    "preferred_username"
                ),
                full_name=supabase_user.get("user_metadata", {}).get("full_name")
                or supabase_user.get("user_metadata", {}).get("name"),
                avatar_url=supabase_user.get("user_metadata", {}).get("avatar_url")
                or supabase_user.get("user_metadata", {}).get("picture"),
                provider=supabase_user.get("app_metadata", {}).get(
                    "provider", "google"
                ),
                provider_id=supabase_user.get("user_metadata", {}).get("sub"),
                is_verified=True,
                last_login=datetime.utcnow(),
            )
            db.add(user)
        else:
            # Update existing user
            logger.info(f"Updating existing user: {user.email}")
            user.last_login = datetime.utcnow()
            user.is_verified = True
            if not user.avatar_url:
                user.avatar_url = supabase_user.get("user_metadata", {}).get(
                    "avatar_url"
                ) or supabase_user.get("user_metadata", {}).get("picture")
            if not user.full_name:
                user.full_name = supabase_user.get("user_metadata", {}).get(
                    "full_name"
                ) or supabase_user.get("user_metadata", {}).get("name")

        db.commit()
        db.refresh(user)

        logger.info(f"Successfully synced user: {user.email}")
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync user: {str(e)}",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get current authenticated user.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Current user data

    Raises:
        HTTPException: If user not found or token invalid
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("Missing or invalid authorization header in /me endpoint")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            logger.warning("Invalid or expired token in /me endpoint")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get user from database
        user = db.query(User).filter(User.id == supabase_user["id"]).first()

        if not user:
            logger.warning(f"User not found in database: {supabase_user['id']}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info(f"Successfully retrieved user: {user.email}")
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user: {str(e)}",
        )
