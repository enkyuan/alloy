"""Transport and device command handlers for Spotify service."""

import logging
from typing import Any, Optional

from app.services.integrations.spotify.exceptions import (
    NoActiveDeviceError,
    SpotifyAPIError,
)
from app.services.integrations.spotify.models import CommandResult

logger = logging.getLogger(__name__)


class SpotifyTransportCommandsMixin:
    """Playback transport, volume, and device switching command handlers."""

    async def pause_playback(self: Any, access_token: str) -> CommandResult:
        """Pause current playback.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming pause

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Pausing playback")

            device_id = await self.get_active_device(access_token)

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Pause requested. Client playback fallback will handle it.",
                    data={"action_required": "client_playback", "action": "pause"},
                )

            await self.client.pause(access_token=access_token, device_id=device_id)

            return CommandResult(success=True, message="Paused playback.", data={})

        except Exception as e:
            logger.error(f"Failed to pause playback: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to pause: {str(e)}", e)

    async def resume_playback(self: Any, access_token: str) -> CommandResult:
        """Resume paused playback.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming resume

        Raises:
            NoActiveDeviceError: If no device available
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Resuming playback")

            device_id = await self.get_active_device(access_token)
            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Resume requested. Client playback fallback will handle it.",
                    data={"action_required": "client_playback", "action": "resume"},
                )

            await self.client.play(access_token=access_token, device_id=device_id)

            return CommandResult(success=True, message="Resumed playback.", data={})

        except Exception as e:
            logger.error(f"Failed to resume playback: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to resume: {str(e)}", e)

    async def next_track(self: Any, access_token: str) -> CommandResult:
        """Skip to next track.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming skip

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Skipping to next track")
            previous_track_id: Optional[str] = None
            try:
                current_playback = await self.client.get_current_playback(access_token)
                previous_track_id = str(current_playback.get("item", {}).get("id", ""))
            except Exception as exc:
                logger.warning(
                    "Failed to snapshot playback before skipping next",
                    extra={"error": str(exc)},
                )

            device_id = await self.get_active_device(access_token)

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Next requested - client should handle",
                    data={"action_required": "client_playback", "action": "next"},
                )

            await self.client.skip_next(access_token=access_token, device_id=device_id)

            verified = await self._verify_track_changed(
                access_token=access_token,
                previous_track_id=previous_track_id or "",
            )
            if verified is False:
                logger.warning(
                    "Next-track verification indicates playback may not have changed",
                    extra={"previous_track_id": previous_track_id},
                )
                return CommandResult(
                    success=True,
                    message=(
                        "Sent next-track command, but I could not confirm a track change. "
                        "Check the active Spotify device."
                    ),
                    data={"verified": False, "previous_track_id": previous_track_id},
                )

            return CommandResult(
                success=True,
                message="Skipped to the next track.",
                data={"verified": verified, "previous_track_id": previous_track_id},
            )

        except Exception as e:
            logger.error(f"Failed to skip track: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to skip: {str(e)}", e)

    async def previous_track(self: Any, access_token: str) -> CommandResult:
        """Skip to previous track.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult confirming skip back

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Skipping to previous track")
            previous_track_id: Optional[str] = None
            try:
                current_playback = await self.client.get_current_playback(access_token)
                previous_track_id = str(current_playback.get("item", {}).get("id", ""))
            except Exception as exc:
                logger.warning(
                    "Failed to snapshot playback before skipping previous",
                    extra={"error": str(exc)},
                )

            device_id = await self.get_active_device(access_token)

            if not device_id:
                logger.info(
                    "No active device found (backend), but returning action for client logic"
                )
                return CommandResult(
                    success=True,
                    message="Previous requested - client should handle",
                    data={"action_required": "client_playback", "action": "previous"},
                )

            await self.client.skip_previous(
                access_token=access_token, device_id=device_id
            )

            verified = await self._verify_track_changed(
                access_token=access_token,
                previous_track_id=previous_track_id or "",
            )
            if verified is False:
                logger.warning(
                    "Previous-track verification indicates playback may not have changed",
                    extra={"previous_track_id": previous_track_id},
                )
                return CommandResult(
                    success=True,
                    message=(
                        "Sent previous-track command, but I could not confirm a track change. "
                        "Check the active Spotify device."
                    ),
                    data={"verified": False, "previous_track_id": previous_track_id},
                )

            return CommandResult(
                success=True,
                message="Went back to the previous track.",
                data={"verified": verified, "previous_track_id": previous_track_id},
            )

        except Exception as e:
            logger.error(f"Failed to skip back: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to skip back: {str(e)}", e)

    async def set_volume(
        self: Any, access_token: str, volume_percent: int
    ) -> CommandResult:
        """Set playback volume.

        Args:
            access_token: Valid Spotify access token
            volume_percent: Volume level (0-100)

        Returns:
            CommandResult confirming volume change

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            # Clamp volume to valid range
            volume_percent = max(0, min(100, volume_percent))

            logger.info(f"Setting volume to {volume_percent}%")

            device_id = await self.get_active_device(access_token)

            await self.client.set_volume(
                access_token=access_token,
                volume_percent=volume_percent,
                device_id=device_id,
            )

            return CommandResult(
                success=True,
                message=f"Volume set to {volume_percent}%",
                data={"volume": volume_percent},
            )

        except Exception as e:
            logger.error(f"Failed to set volume: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to set volume: {str(e)}", e)

    async def get_available_devices(self: Any, access_token: str) -> CommandResult:
        """Get list of available devices.

        Args:
            access_token: Valid Spotify access token

        Returns:
            CommandResult with device list

        Raises:
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info("Getting available devices")

            devices_response = await self.client.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            device_list = [
                {
                    "id": d["id"],
                    "name": d["name"],
                    "type": d["type"],
                    "is_active": d.get("is_active", False),
                    "volume_percent": d.get("volume_percent", 0),
                }
                for d in devices
            ]

            if not devices:
                message = "No devices available"
            else:
                device_names = [d["name"] for d in device_list]
                message = f"Available devices: {', '.join(device_names)}"

            return CommandResult(
                success=True, message=message, data={"devices": device_list}
            )

        except Exception as e:
            logger.error(f"Failed to get devices: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to get devices: {str(e)}", e)

    async def switch_device(
        self: Any,
        access_token: str,
        device_name: Optional[str] = None,
        device_id: Optional[str] = None,
        start_playback: bool = True,
    ) -> CommandResult:
        """Switch playback to a different device.

        Args:
            access_token: Valid Spotify access token
            device_name: Name of device to switch to (fuzzy matched)
            device_id: Specific device ID to switch to
            start_playback: Whether to start playing on the new device

        Returns:
            CommandResult confirming device switch

        Raises:
            NoActiveDeviceError: If no matching device found
            SpotifyAPIError: If API call fails
        """
        try:
            logger.info(f"Switching device: name={device_name}, id={device_id}")

            # Get available devices
            devices_response = await self.client.get_available_devices(access_token)
            devices = devices_response.get("devices", [])

            if not devices:
                raise NoActiveDeviceError("No devices available to switch to")

            # Find target device
            target_device = None

            if device_id:
                # Find by exact ID
                target_device = next((d for d in devices if d["id"] == device_id), None)
            elif device_name:
                # Find by name (case-insensitive, fuzzy match)
                device_name_lower = device_name.lower()

                # First try exact match
                target_device = next(
                    (d for d in devices if d["name"].lower() == device_name_lower), None
                )

                # If no exact match, try partial match
                if not target_device:
                    target_device = next(
                        (d for d in devices if device_name_lower in d["name"].lower()),
                        None,
                    )

            if not target_device:
                available_names = [d["name"] for d in devices]
                raise NoActiveDeviceError(
                    f"Device '{device_name or device_id}' not found. "
                    f"Available devices: {', '.join(available_names)}"
                )

            # Transfer playback to target device
            await self.client.transfer_playback(
                access_token=access_token,
                device_id=target_device["id"],
                play=start_playback,
            )

            logger.info(f"Successfully switched to device: {target_device['name']}")

            return CommandResult(
                success=True,
                message=f"Switched playback to {target_device['name']}",
                data={
                    "device_id": target_device["id"],
                    "device_name": target_device["name"],
                    "device_type": target_device["type"],
                },
            )

        except NoActiveDeviceError:
            raise
        except Exception as e:
            logger.error(f"Failed to switch device: {str(e)}", exc_info=True)
            raise SpotifyAPIError(f"Failed to switch device: {str(e)}", e)
