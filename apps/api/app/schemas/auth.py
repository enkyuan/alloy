"""Authentication schemas for request/response validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# Base Schemas

class UserBase(BaseModel):
    """Base user schema with common fields.
    
    Attributes:
        email: User's email address
        username: Optional username
        full_name: User's full name
    """
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """Schema for creating a new user.
    
    Attributes:
        provider: OAuth provider (google, apple, email)
        provider_id: Provider-specific user ID
    """
    provider: str = "email"
    provider_id: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for updating user information.
    
    All fields are optional to allow partial updates.
    """
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


# Response Schemas

class UserInDB(UserBase):
    """Schema for user data from database.
    
    This includes all database fields including timestamps.
    """
    id: str
    avatar_url: Optional[str] = None
    provider: str
    provider_id: Optional[str] = None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserResponse(UserBase):
    """Schema for user response sent to clients.
    
    This is a sanitized version that excludes sensitive data.
    """
    id: str
    avatar_url: Optional[str] = None
    provider: str
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# OAuth Request Schemas

class GoogleOAuthRequest(BaseModel):
    """Schema for Google OAuth token exchange.
    
    Note: This is kept for potential server-side OAuth but not currently used.
    The iOS app uses Supabase SDK directly.
    """
    id_token: str = Field(..., description="Google ID token from client")
    nonce: Optional[str] = Field(None, description="Nonce used in Google Sign-In")


class AppleOAuthRequest(BaseModel):
    """Schema for Apple Sign In.
    
    Note: This is kept for potential server-side OAuth but not currently used.
    The iOS app uses Supabase SDK directly.
    """
    id_token: str = Field(..., description="Apple ID token from client")
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None


# Token Schemas

class TokenResponse(BaseModel):
    """Schema for authentication token response.
    
    Attributes:
        access_token: JWT access token
        token_type: Token type (always "bearer")
        expires_in: Token expiration time in seconds
        refresh_token: Optional refresh token
        user: User information
    """
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh request.
    
    Attributes:
        refresh_token: Refresh token to exchange for new access token
    """
    refresh_token: str
