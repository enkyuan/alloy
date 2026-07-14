"""Configuration owned by the reference service."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, Literal, Optional, overload

from kaji.core.config import Settings as SDKSettings


class Settings(SDKSettings):
    """SDK settings plus infrastructure required by ``kaji-serve``."""

    DATABASE_URL: str = ""

    SUPABASE_URL: Optional[str] = None
    SUPABASE_KONG_URL: Optional[str] = None
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    JWT_SECRET: str = ""
    JWT_ISSUER: str = ""
    JWT_AUDIENCE: str = ""

    SONIOX_API_KEY: Optional[str] = None

    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Kaji Serve"
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    def model_post_init(self, __context: Any) -> None:
        if not self.SUPABASE_KONG_URL and self.SUPABASE_URL:
            self.SUPABASE_KONG_URL = self.SUPABASE_URL
        if not self.SUPABASE_SERVICE_ROLE_KEY and self.SUPABASE_SERVICE_KEY:
            self.SUPABASE_SERVICE_ROLE_KEY = self.SUPABASE_SERVICE_KEY

    @property
    def cors_allow_origins(self) -> list[str]:
        origins = [
            origin.strip()
            for origin in self.CORS_ALLOW_ORIGINS.split(",")
            if origin.strip()
        ]
        return origins or ["http://localhost:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide service settings."""
    return Settings()


if TYPE_CHECKING:
    settings: Settings


@overload
def __getattr__(name: Literal["settings"]) -> Settings: ...


@overload
def __getattr__(name: str) -> Any: ...


def __getattr__(name: str) -> Any:
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
