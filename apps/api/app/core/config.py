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
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KONG_URL: Optional[str] = None
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

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
    SPOTIFY_REDIRECT_URI: str = "havenos://spotify/callback"

    # Discord OAuth
    DISCORD_CLIENT_ID: Optional[str] = None
    DISCORD_CLIENT_SECRET: Optional[str] = None
    DISCORD_REDIRECT_URI: Optional[str] = None
    DISCORD_API_BASE_URL: str = "https://discord.com/api/v10"

    # Todoist OAuth
    TODOIST_CLIENT_ID: Optional[str] = None
    TODOIST_CLIENT_SECRET: Optional[str] = None
    TODOIST_REDIRECT_URI: Optional[str] = None
    TODOIST_API_BASE_URL: str = "https://api.todoist.com/rest/v2"

    # Calendly OAuth
    CALENDLY_CLIENT_ID: Optional[str] = None
    CALENDLY_CLIENT_SECRET: Optional[str] = None
    CALENDLY_REDIRECT_URI: Optional[str] = None
    CALENDLY_API_BASE_URL: str = "https://api.calendly.com"

    # Gmail OAuth (reuses Google OAuth credentials)
    # No separate credentials needed - uses GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
    GMAIL_REDIRECT_URI: Optional[str] = None

    # Soniox (Real-time Speech-to-Text)
    SONIOX_API_KEY: Optional[str] = None

    # Google Gemini AI
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"

    # Application
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Modal API"

    # TaskIQ
    TASKIQ_BROKER: str = "redis"  # Options: redis
    TASKIQ_RESULT_BACKEND: str = "redis"

    # Agent pipeline
    AGENT_HISTORY_LIMIT: Optional[int] = 200
    AGENT_CACHE_TTL_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # No extra runtime overrides.
        # Fallback logic for Supabase URLs and Keys
        if not self.SUPABASE_KONG_URL and self.SUPABASE_URL:
            self.SUPABASE_KONG_URL = self.SUPABASE_URL

        if not self.SUPABASE_SERVICE_ROLE_KEY and self.SUPABASE_SERVICE_KEY:
            self.SUPABASE_SERVICE_ROLE_KEY = self.SUPABASE_SERVICE_KEY

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
