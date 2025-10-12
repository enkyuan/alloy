"""Authentication routes for OAuth and user management."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    GoogleOAuthRequest,
    AppleOAuthRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
)
from app.services.supabase_auth import supabase_auth_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/google", response_model=TokenResponse)
async def google_oauth(
    request: GoogleOAuthRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user with Google OAuth.

    This endpoint accepts a Google ID token from the iOS app,
    verifies it with Supabase, and creates/updates the user in our database.

    Args:
        request: Google OAuth request containing ID token
        db: Database session

    Returns:
        TokenResponse with access token and user data

    Raises:
        HTTPException: If authentication fails
    """
    try:
        # Verify Google token with Supabase
        supabase_response = await supabase_auth_service.verify_google_token(
            request.id_token
        )

        # Extract user data from Supabase response
        supabase_user = supabase_response.get("user")
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token"
            )

        # Get or create user in our database
        user = db.query(User).filter(
            User.email == supabase_user["email"]
        ).first()

        if not user:
            # Create new user
            user = User(
                id=supabase_user["id"],
                email=supabase_user["email"],
                username=supabase_user.get("user_metadata", {}).get("preferred_username"),
                full_name=supabase_user.get("user_metadata", {}).get("full_name") or
                          supabase_user.get("user_metadata", {}).get("name"),
                avatar_url=supabase_user.get("user_metadata", {}).get("avatar_url") or
                          supabase_user.get("user_metadata", {}).get("picture"),
                provider="google",
                provider_id=supabase_user.get("user_metadata", {}).get("sub"),
                is_verified=True,
                last_login=datetime.utcnow()
            )
            db.add(user)
        else:
            # Update existing user
            user.last_login = datetime.utcnow()
            user.is_verified = True
            if not user.avatar_url:
                user.avatar_url = supabase_user.get("user_metadata", {}).get("avatar_url") or \
                                 supabase_user.get("user_metadata", {}).get("picture")
            if not user.full_name:
                user.full_name = supabase_user.get("user_metadata", {}).get("full_name") or \
                                supabase_user.get("user_metadata", {}).get("name")

        db.commit()
        db.refresh(user)

        # Return token response
        return TokenResponse(
            access_token=supabase_response["access_token"],
            token_type="bearer",
            expires_in=supabase_response.get("expires_in", 3600),
            refresh_token=supabase_response.get("refresh_token"),
            user=UserResponse.model_validate(user)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/apple", response_model=TokenResponse)
async def apple_oauth(
    request: AppleOAuthRequest,
    db: Session = Depends(get_db)
):
    """Authenticate user with Apple Sign In.

    This endpoint accepts an Apple ID token from the iOS app,
    verifies it with Supabase, and creates/updates the user in our database.

    Args:
        request: Apple OAuth request containing ID token
        db: Database session

    Returns:
        TokenResponse with access token and user data

    Raises:
        HTTPException: If authentication fails
    """
    try:
        # Verify Apple token with Supabase
        supabase_response = await supabase_auth_service.verify_apple_token(
            request.id_token
        )

        # Extract user data from Supabase response
        supabase_user = supabase_response.get("user")
        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Apple token"
            )

        # Get or create user in our database
        user = db.query(User).filter(
            User.email == supabase_user["email"]
        ).first()

        if not user:
            # Create new user
            user = User(
                id=supabase_user["id"],
                email=supabase_user["email"],
                username=supabase_user.get("user_metadata", {}).get("preferred_username"),
                full_name=supabase_user.get("user_metadata", {}).get("full_name") or
                          request.user_info.get("name", {}).get("firstName") if request.user_info else None,
                provider="apple",
                provider_id=supabase_user.get("user_metadata", {}).get("sub"),
                is_verified=True,
                last_login=datetime.utcnow()
            )
            db.add(user)
        else:
            # Update existing user
            user.last_login = datetime.utcnow()
            user.is_verified = True

        db.commit()
        db.refresh(user)

        # Return token response
        return TokenResponse(
            access_token=supabase_response["access_token"],
            token_type="bearer",
            expires_in=supabase_response.get("expires_in", 3600),
            refresh_token=supabase_response.get("refresh_token"),
            user=UserResponse.model_validate(user)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
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
        user = db.query(User).filter(User.id == supabase_user["id"]).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        return TokenResponse(
            access_token=supabase_response["access_token"],
            token_type="bearer",
            expires_in=supabase_response.get("expires_in", 3600),
            refresh_token=supabase_response.get("refresh_token"),
            user=UserResponse.model_validate(user)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    access_token: str,
    db: Session = Depends(get_db)
):
    """Get current authenticated user.

    Args:
        access_token: Supabase access token (from Authorization header)
        db: Database session

    Returns:
        Current user data

    Raises:
        HTTPException: If user not found or token invalid
    """
    try:
        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        # Get user from database
        user = db.query(User).filter(User.id == supabase_user["id"]).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        return UserResponse.model_validate(user)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user: {str(e)}"
        )
