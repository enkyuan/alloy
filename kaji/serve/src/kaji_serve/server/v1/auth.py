"""Authentication routes for OAuth and user management."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kaji.core.safe_logging import log_redacted_failure
from kaji_serve.server.deps import get_current_supabase_user
from kaji_serve.server.supabase_auth import supabase_auth_service
from kaji_serve.server.database import get_db
from kaji_serve.server.models.user import User
from kaji_serve.server.models.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token."""
    try:
        supabase_response = await supabase_auth_service.refresh_token(
            request.refresh_token
        )

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
            logger.warning("Authenticated user not found in database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info("Successfully refreshed user token")
        return TokenResponse(
            access_token=supabase_response["access_token"],
            token_type="bearer",
            expires_in=supabase_response.get("expires_in", 3600),
            refresh_token=supabase_response.get("refresh_token"),
            user=UserResponse.model_validate(user),
        )

    except HTTPException:
        raise
    except Exception as error:
        log_redacted_failure(
            logger,
            logging.ERROR,
            "Token refresh failed",
            error,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed",
        )


@router.post("/sync", response_model=UserResponse)
async def sync_user(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync user from Supabase to our database."""
    try:
        result = await db.execute(select(User).where(User.id == supabase_user["id"]))
        user = result.scalar_one_or_none()

        if not user:
            logger.info("Creating authenticated user")
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
            logger.info("Updating authenticated user")
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

        logger.info("Successfully synced authenticated user")
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as error:
        log_redacted_failure(
            logger,
            logging.ERROR,
            "Failed to sync user",
            error,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync user",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated user."""
    try:
        result = await db.execute(select(User).where(User.id == supabase_user["id"]))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("Authenticated user not found in database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.info("Successfully retrieved authenticated user")
        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as error:
        log_redacted_failure(
            logger,
            logging.ERROR,
            "Failed to get user",
            error,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user",
        )
