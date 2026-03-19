"""Google token refresh helpers for workspace integrations."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.integration import Integration
from app.services.integrations.base import ExpiringOAuthIntegrationService


class WorkspaceGoogleAuthService(ExpiringOAuthIntegrationService):
    """OAuth token helper for Gmail/Calendar workspace integrations."""

    SERVICE_NAME = "google"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    DEFAULT_EXPIRES_IN_SECONDS = 3600
    TOKEN_REFRESH_WINDOW = timedelta(minutes=5)

    def __init__(self) -> None:
        super().__init__(max_connections=40, max_keepalive_connections=15)

    def _oauth_client_credentials(self) -> tuple[str | None, str | None]:
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET


workspace_google_auth_service = WorkspaceGoogleAuthService()


async def close_workspace_http_client() -> None:
    """Backward-compatible close helper for legacy shutdown paths."""
    await workspace_google_auth_service.close()


async def get_valid_google_token(integration: Integration, db: AsyncSession) -> str:
    """Get valid Google access token, refreshing when near expiry."""
    return await workspace_google_auth_service.get_valid_token(integration, db)
