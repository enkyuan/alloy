"""Discord API service."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.services.integrations.base import ExpiringOAuthIntegrationService


class DiscordService(ExpiringOAuthIntegrationService):
    """Service for Discord API operations."""

    SERVICE_NAME = "discord"
    BASE_URL = settings.DISCORD_API_BASE_URL
    TOKEN_URL = "https://discord.com/api/oauth2/token"
    DEFAULT_EXPIRES_IN_SECONDS = 604800
    TOKEN_REFRESH_WINDOW = timedelta(hours=1)

    def _oauth_client_credentials(self) -> tuple[str | None, str | None]:
        return settings.DISCORD_CLIENT_ID, settings.DISCORD_CLIENT_SECRET

    async def get_current_user(self, access_token: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/users/@me",
            action="get current user",
            headers=self._auth_headers(access_token),
        )

    async def get_user_guilds(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/users/@me/guilds",
            action="get user guilds",
            headers=self._auth_headers(access_token),
        )

    async def get_user_connections(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/users/@me/connections",
            action="get user connections",
            headers=self._auth_headers(access_token),
        )

    async def get_guild(self, access_token: str, guild_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/guilds/{guild_id}",
            action="get guild",
            headers=self._auth_headers(access_token),
        )

    async def get_guild_channels(
        self,
        access_token: str,
        guild_id: str,
    ) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/guilds/{guild_id}/channels",
            action="get guild channels",
            headers=self._auth_headers(access_token),
        )

    async def get_guild_members(
        self,
        access_token: str,
        guild_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/guilds/{guild_id}/members",
            action="get guild members",
            headers=self._auth_headers(access_token),
            params={"limit": min(limit, 1000)},
        )

    async def get_channel(self, access_token: str, channel_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/channels/{channel_id}",
            action="get channel",
            headers=self._auth_headers(access_token),
        )

    async def get_channel_messages(
        self,
        access_token: str,
        channel_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/channels/{channel_id}/messages",
            action="get channel messages",
            headers=self._auth_headers(access_token),
            params={"limit": min(limit, 100)},
        )

    async def send_message(
        self,
        access_token: str,
        channel_id: str,
        content: str,
        tts: bool = False,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/channels/{channel_id}/messages",
            action="send message",
            headers=self._auth_headers(access_token),
            json={"content": content, "tts": tts},
            expected_status=(200, 201),
        )

    async def delete_message(
        self,
        access_token: str,
        channel_id: str,
        message_id: str,
    ) -> None:
        await self._request_no_content(
            "DELETE",
            f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}",
            action="delete message",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def add_reaction(
        self,
        access_token: str,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> None:
        await self._request_no_content(
            "PUT",
            f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
            action="add reaction",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def get_voice_regions(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/voice/regions",
            action="get voice regions",
            headers=self._auth_headers(access_token),
        )

    async def create_dm(
        self,
        access_token: str,
        recipient_id: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/users/@me/channels",
            action="create dm",
            headers=self._auth_headers(access_token),
            json={"recipient_id": recipient_id},
            expected_status=(200, 201),
        )


discord_service = DiscordService()
