"""Discord API service."""
<<<<<<< HEAD

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
=======
>>>>>>> codex/refactor

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

<<<<<<< HEAD
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://discord.com/api/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": integration.refresh_token,
                        "client_id": settings.DISCORD_CLIENT_ID,
                        "client_secret": settings.DISCORD_CLIENT_SECRET,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

                if response.status_code != 200:
                    logger.error(f"Discord token refresh failed: {response.text}")
                    raise Exception(f"Failed to refresh token: {response.text}")

                token_data = response.json()

                # Update integration
                integration.access_token = token_data["access_token"]
                integration.expires_at = datetime.utcnow() + timedelta(
                    seconds=token_data.get(
                        "expires_in", 604800
                    )  # Discord tokens last 7 days
                )
                integration.updated_at = datetime.utcnow()

                if "refresh_token" in token_data:
                    integration.refresh_token = token_data["refresh_token"]

                db.commit()

                logger.info(
                    f"Successfully refreshed Discord token for user {integration.user_id}"
                )
                return integration.access_token

        except Exception as e:
            logger.error(f"Failed to refresh Discord token: {str(e)}", exc_info=True)
            raise

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
        """Get valid access token, refreshing if needed.

        Args:
            integration: Integration model
            db: Database session

        Returns:
            Valid access token

        Raises:
            Exception: If token refresh fails
        """
        # Check if token is expired or expires soon (within 1 hour)
        if (
            integration.expires_at
            and integration.expires_at < datetime.utcnow() + timedelta(hours=1)
        ):
            logger.info("Discord token expired or expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return integration.access_token

    # ============================================================================
    # User
    # ============================================================================

    async def get_current_user(self, access_token: str) -> Dict[str, Any]:
        """Get current user's Discord profile.

        Args:
            access_token: Valid Discord access token

        Returns:
            User profile data

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get user profile: {response.text}")

            return response.json()

    async def get_user_guilds(self, access_token: str) -> List[Dict[str, Any]]:
        """Get guilds (servers) the user is a member of.

        Args:
            access_token: Valid Discord access token

        Returns:
            List of guilds

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/users/@me/guilds",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get guilds: {response.text}")

            return response.json()

    async def get_user_connections(self, access_token: str) -> List[Dict[str, Any]]:
        """Get user's connected accounts.

        Args:
            access_token: Valid Discord access token

        Returns:
            List of connections

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/users/@me/connections",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get connections: {response.text}")

            return response.json()

    # ============================================================================
    # Guilds
    # ============================================================================

    async def get_guild(self, access_token: str, guild_id: str) -> Dict[str, Any]:
        """Get guild details.

        Args:
            access_token: Valid Discord access token
            guild_id: Guild ID

        Returns:
            Guild details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/guilds/{guild_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get guild: {response.text}")

            return response.json()

    async def get_guild_channels(
        self, access_token: str, guild_id: str
    ) -> List[Dict[str, Any]]:
        """Get channels in a guild.

        Args:
            access_token: Valid Discord access token
            guild_id: Guild ID

        Returns:
            List of channels

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/guilds/{guild_id}/channels",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get channels: {response.text}")

            return response.json()

    async def get_guild_members(
        self, access_token: str, guild_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get members in a guild.

        Args:
            access_token: Valid Discord access token
            guild_id: Guild ID
            limit: Number of members to return (max 1000)

        Returns:
            List of members

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/guilds/{guild_id}/members",
                params={"limit": min(limit, 1000)},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get members: {response.text}")

            return response.json()

    # ============================================================================
    # Channels & Messages
    # ============================================================================

    async def get_channel(self, access_token: str, channel_id: str) -> Dict[str, Any]:
        """Get channel details.

        Args:
            access_token: Valid Discord access token
            channel_id: Channel ID

        Returns:
            Channel details

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/channels/{channel_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get channel: {response.text}")

            return response.json()

    async def get_channel_messages(
        self, access_token: str, channel_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get messages from a channel.

        Args:
            access_token: Valid Discord access token
            channel_id: Channel ID
            limit: Number of messages to return (max 100)

        Returns:
            List of messages

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/channels/{channel_id}/messages",
                params={"limit": min(limit, 100)},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get messages: {response.text}")

            return response.json()

    async def send_message(
        self, access_token: str, channel_id: str, content: str, tts: bool = False
    ) -> Dict[str, Any]:
        """Send a message to a channel.

        Args:
            access_token: Valid Discord access token
            channel_id: Channel ID
            content: Message content
            tts: Whether to use text-to-speech

        Returns:
            Created message

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/channels/{channel_id}/messages",
                json={"content": content, "tts": tts},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to send message: {response.text}")

            return response.json()

    async def delete_message(
        self, access_token: str, channel_id: str, message_id: str
    ) -> None:
        """Delete a message.

        Args:
            access_token: Valid Discord access token
            channel_id: Channel ID
            message_id: Message ID

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to delete message: {response.text}")

    async def add_reaction(
        self, access_token: str, channel_id: str, message_id: str, emoji: str
=======
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
>>>>>>> codex/refactor
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

<<<<<<< HEAD
        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.BASE_URL}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to add reaction: {response.text}")

    # ============================================================================
    # Voice
    # ============================================================================

    async def get_voice_regions(self, access_token: str) -> List[Dict[str, Any]]:
        """Get available voice regions.

        Args:
            access_token: Valid Discord access token

        Returns:
            List of voice regions

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/voice/regions",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get voice regions: {response.text}")

            return response.json()

    # ============================================================================
    # DMs
    # ============================================================================

    async def create_dm(self, access_token: str, recipient_id: str) -> Dict[str, Any]:
        """Create a DM channel with a user.

        Args:
            access_token: Valid Discord access token
            recipient_id: User ID to create DM with

        Returns:
            DM channel

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/users/@me/channels",
                json={"recipient_id": recipient_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create DM: {response.text}")

            return response.json()
=======
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
>>>>>>> codex/refactor


discord_service = DiscordService()
