"""Application configuration and settings management."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Optional, overload

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SDK settings loaded from environment variables.

    All settings are loaded from the .env file or environment variables.
    Required settings will raise an error if not provided.
    """

    # Redis (optional realtime/session adapters)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Text-to-Speech
    TTS_PROVIDER: str = "none"  # Options: none, gemini, openai
    # Voice and model are provider-specific. Leave empty to use the selected
    # provider's own default (see each TTS service's DEFAULT_VOICE/DEFAULT_MODEL).
    TTS_VOICE: str = ""
    TTS_MODEL: str = ""

    # Agent Provider Config
    KAJI_MODEL_PROVIDER: str = "mock"

    # OpenRouter / Kimi
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_HTTP_REFERER: Optional[str] = None
    OPENROUTER_APP_TITLE: Optional[str] = None
    KIMI_MODEL: str = "moonshotai/kimi-k2.6"

    # Cloudflare AI (Optional)
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_KIMI_MODEL: str = "@cf/moonshotai/kimi-k2.6"

    # Google Gemini AI
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.5-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-2"

    # OpenAI (LLM provider + TTS)
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-5.4-mini"
    OPENAI_BASE_URL: Optional[str] = None

    # Anthropic
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, constructed on first use.

    Construction is deferred (rather than instantiated at import time) so that
    ``import kaji`` works without any environment configured. The result is
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
    # subpackages that do ``from kaji.core.config import settings``) does
    # not construct Settings() until an attribute is actually read.
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
