"""Authentication routes for OAuth and user management."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.routers.dependencies import get_current_supabase_user
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
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
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
        if not supabase_user:
            logger.warning("No user found in Supabase response")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in Supabase",
            )

        result = await db.execute(select(User).where(User.id == supabase_user["id"]))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("User not found in database: %s", supabase_user["id"])
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info("Successfully refreshed token for user: %s", user.email)
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
        logger.error("Token refresh failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed",
        )


@router.post("/sync", response_model=UserResponse)
async def sync_user(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync user from Supabase to our database.

    Called by iOS app after successful Supabase authentication.
    This endpoint creates or updates the user in our local database.

    Args:
        supabase_user: Authenticated user from Supabase dependency
        db: Database session

    Returns:
        UserResponse with synced user data

    Raises:
        HTTPException: If authentication fails or sync error occurs
    """
    try:
        # Get or create user in our database
        result = await db.execute(select(User).where(User.id == supabase_user["id"]))
        user = result.scalar_one_or_none()

        if not user:
            # Create new user
            logger.info("Creating new user: %s", supabase_user["email"])
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
                last_login=datetime.now(timezone.utc),
            )
            db.add(user)
        else:
            # Update existing user
            logger.info("Updating existing user: %s", user.email)
            user.last_login = datetime.now(timezone.utc)
            user.is_verified = True
            if not user.avatar_url:
                user.avatar_url = supabase_user.get("user_metadata", {}).get(
                    "avatar_url"
                ) or supabase_user.get("user_metadata", {}).get("picture")
            if not user.full_name:
                user.full_name = supabase_user.get("user_metadata", {}).get(
                    "full_name"
                ) or supabase_user.get("user_metadata", {}).get("name")

        await db.commit()
        await db.refresh(user)

        logger.info("Successfully synced user: %s", user.email)
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to sync user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync user",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated user.

    Args:
        supabase_user: Authenticated user from Supabase dependency
        db: Database session

    Returns:
        Current user data

    Raises:
        HTTPException: If user not found or token invalid
    """
    try:
        # Get user from database
        result = await db.execute(select(User).where(User.id == supabase_user["id"]))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("User not found in database: %s", supabase_user["id"])
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info("Successfully retrieved user: %s", user.email)
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user",
        )
