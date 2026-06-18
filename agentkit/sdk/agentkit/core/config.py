"""Application configuration and settings management."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Optional, overload

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings are loaded from the .env file or environment variables.
    Required settings will raise an error if not provided.
    """

    # NOTE: DATABASE_URL, SUPABASE_ANON_KEY, and JWT_SECRET default to empty so
    # the core SDK imports and `get_settings()` works with no environment. They
    # are required by the serve stack (agentkit-serve); the database, auth, and
    # token code raises clearly if used while unset.

    # Database
    DATABASE_URL: str = ""

    # Redis (for future caching/sessions)
    REDIS_URL: str = "redis://redis:6379/0"

    # Supabase (SUPABASE_KONG_URL is the internal Docker network URL)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KONG_URL: Optional[str] = None
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # JWT (for custom tokens if needed)
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    TOKEN_ENCRYPTION_KEY: Optional[str] = None

    # Soniox (Real-time Speech-to-Text)
    SONIOX_API_KEY: Optional[str] = None

    # Text-to-Speech
    TTS_PROVIDER: str = "none"  # Options: none, gemini, openai
    # Voice and model are provider-specific. Leave empty to use the selected
    # provider's own default (see each TTS service's DEFAULT_VOICE/DEFAULT_MODEL).
    TTS_VOICE: str = ""
    TTS_MODEL: str = ""

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

    # OpenAI (LLM provider + TTS)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: Optional[str] = None

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # Application
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "AgentKit SDK"
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, constructed on first use.

    Construction is deferred (rather than instantiated at import time) so that
    ``import agentkit`` works without any environment configured. The result is
    cached, so every caller shares one mutable instance. Tests that need a fresh
    instance for different env can call ``get_settings.cache_clear()``.
    """
    return Settings()


if TYPE_CHECKING:
    # Provides a typed ``settings`` attribute for type checkers (PEP 562).
    # At runtime the value is supplied by ``__getattr__`` below.
    settings: Settings


@overload
def __getattr__(name: Literal["settings"]) -> Settings: ...


@overload
def __getattr__(name: str) -> Any: ...


def __getattr__(name: str) -> Any:
    # PEP 562: resolve ``settings`` lazily so importing this module (and the
    # subpackages that do ``from agentkit.core.config import settings``) does
    # not construct Settings() until an attribute is actually read.
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
