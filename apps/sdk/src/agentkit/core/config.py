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

    # Soniox (Real-time Speech-to-Text)
    SONIOX_API_KEY: Optional[str] = None

    # Text-to-Speech
    TTS_PROVIDER: str = "none"  # Options: none, gemini
    TTS_VOICE: str = "Kore"  # Prebuilt voice name (provider-specific)
    TTS_MODEL: str = "gemini-2.5-flash-preview-tts"

    # Agent Provider Config
    AGENTKIT_MODEL_PROVIDER: str = "kimi"

    # OpenRouter / Kimi
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_HTTP_REFERER: Optional[str] = None
    OPENROUTER_APP_TITLE: Optional[str] = None

    # Legacy Kimi fields (still supported as fallback)
    KIMI_API_KEY: Optional[str] = None
    KIMI_MODEL: str = "moonshotai/kimi-k2.6"
    KIMI_BASE_URL: Optional[str] = None

    # Cloudflare AI (Optional)
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_KIMI_MODEL: str = "@cf/moonshotai/kimi-k2.6"

    # Google Gemini AI
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"

    # Application
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "AgentKit SDK"
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # TaskIQ
    TASKIQ_BROKER: str = "redis"  # Options: redis
    TASKIQ_RESULT_BACKEND: str = "redis"

    # Agent pipeline
    AGENT_HISTORY_LIMIT: Optional[int] = 200
    AGENT_CACHE_TTL_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )

    def model_post_init(self, __context: Any) -> None:
        # Fallback logic for Supabase URLs and keys.
        if not self.SUPABASE_KONG_URL and self.SUPABASE_URL:
            self.SUPABASE_KONG_URL = self.SUPABASE_URL

        if not self.SUPABASE_SERVICE_ROLE_KEY and self.SUPABASE_SERVICE_KEY:
            self.SUPABASE_SERVICE_ROLE_KEY = self.SUPABASE_SERVICE_KEY

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
