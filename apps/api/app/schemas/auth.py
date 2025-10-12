"""Authentication schemas for request/response validation."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    username: Optional[str] = None
    full_name: Optional[str] = None


class UserCreate(UserBase):
    """Schema for creating a new user."""
    provider: str = "email"
    provider_id: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema for updating user information."""
    username: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserInDB(UserBase):
    """Schema for user data from database."""
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
    """Schema for user response."""
    id: str
    avatar_url: Optional[str] = None
    provider: str
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class GoogleOAuthRequest(BaseModel):
    """Schema for Google OAuth token exchange."""
    id_token: str = Field(..., description="Google ID token from client")


class AppleOAuthRequest(BaseModel):
    """Schema for Apple Sign In."""
    id_token: str = Field(..., description="Apple ID token from client")
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None


class TokenResponse(BaseModel):
    """Schema for authentication token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh request."""
    refresh_token: str
