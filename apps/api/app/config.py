"""Application configuration and settings management."""
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    All settings are loaded from the .env file or environment variables.
    Required settings will raise an error if not provided.
    """

    # Database
    DATABASE_URL: str

    # Redis (for future caching/sessions)
    REDIS_URL: str = "redis://redis:6379/0"

    # Supabase (SUPABASE_KONG_URL is the internal Docker network URL)
    SUPABASE_KONG_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str

    # JWT (for custom tokens if needed)
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Google OAuth (optional - used for server-side OAuth)
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # Apple OAuth (optional - used for server-side OAuth)
    APPLE_CLIENT_ID: Optional[str] = None
    APPLE_TEAM_ID: Optional[str] = None
    APPLE_KEY_ID: Optional[str] = None
    APPLE_PRIVATE_KEY: Optional[str] = None

    # Spotify OAuth
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None
    SPOTIFY_REDIRECT_URI: str = "modal://spotify/callback"

    # Uber OAuth
    UBER_CLIENT_ID: Optional[str] = None
    UBER_CLIENT_SECRET: Optional[str] = None
    UBER_REDIRECT_URI: str = "modal://uber/callback"

    # Gmail OAuth (reuses Google OAuth credentials)
    # No separate credentials needed - uses GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
    GMAIL_REDIRECT_URI: Optional[str] = None

    # Soniox (Real-time Speech-to-Text)
    SONIOX_API_KEY: Optional[str] = None

    # Application
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Modal API"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True
    )
    
    # Computed properties - Gmail reuses Google OAuth credentials
    @property
    def GMAIL_CLIENT_ID(self) -> Optional[str]:
        """Gmail uses the same Google OAuth client ID."""
        return self.GOOGLE_CLIENT_ID
    
    @property
    def GMAIL_CLIENT_SECRET(self) -> Optional[str]:
        """Gmail uses the same Google OAuth client secret."""
        return self.GOOGLE_CLIENT_SECRET


# Global settings instance
settings = Settings()
