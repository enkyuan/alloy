"""Application configuration and settings management."""

from typing import Any, Optional

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
    TOKEN_ENCRYPTION_KEY: Optional[str] = None

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
    SPOTIFY_REDIRECT_URI: Optional[str] = None

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
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # TaskIQ
    TASKIQ_BROKER: str = "redis"  # Options: redis
    TASKIQ_RESULT_BACKEND: str = "redis"

    # Agent pipeline
    AGENT_HISTORY_LIMIT: Optional[int] = 200
    AGENT_CACHE_TTL_SECONDS: int = 300
    AGENT_SPOTIFY_CACHE_TTL_SECONDS: int = 3600
    AGENT_CLIENT_HINT_CONTROL_MIN_CONFIDENCE: float = 0.82
    AGENT_CLIENT_HINT_PLAY_MIN_CONFIDENCE: float = 0.93
    SPOTIFY_DISABLE_CLARIFICATION_MESSAGES: bool = True
    SPOTIFY_RESOLVER_MEMORY_TTL_SECONDS: int = 30 * 24 * 60 * 60
    SPOTIFY_RESOLVER_MEMORY_MAX_URIS: int = 8

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    def model_post_init(self, __context: Any) -> None:
        # Fallback logic for Supabase URLs and keys.
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

    @property
    def cors_allow_origins(self) -> list[str]:
        """Return parsed CORS origins from comma-delimited config."""
        origins = [
            origin.strip()
            for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip()
        ]
        if origins:
            return origins
        # Safe default for local frontend development.
        return ["http://localhost:3000"]


# Global settings instance
settings = Settings()
