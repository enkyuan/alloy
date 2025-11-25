"""Voice agent service for command orchestration."""

import logging
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings
from app.services.pipeline.cmd_parser import (
    CommandContext,
    CommandIntent,
    CommandParser,
    command_parser,
)

logger = logging.getLogger(__name__)

# Redis client
redis_client = redis.from_url(
    settings.REDIS_URL, encoding="utf-8", decode_responses=True
)


@dataclass
class CommandResult:
    """Result of command execution."""

    success: bool
    message: str  # User-friendly response message
    data: dict  # Additional data (track info, etc.)
    error: Optional[str] = None


class VoiceAgentService:
    """Orchestrates voice command processing and response generation."""

    def __init__(self, parser: Optional[CommandParser] = None):
        """Initialize voice agent service.

        Args:
            parser: Optional CommandParser instance (uses singleton if not provided)
        """
        self.parser = parser or command_parser

    async def get_context(self, user_id: str) -> CommandContext:
        """Get command context for a user from Redis.

        Args:
            user_id: User identifier

        Returns:
            CommandContext for the user
        """
        key = f"voice_context:{user_id}"
        data = await redis_client.get(key)

        context = CommandContext(user_id=user_id)

        if data:
            try:
                data_dict = json.loads(data)
                # Restore context fields
                context.last_command = data_dict.get("last_command")
                context.last_intent = data_dict.get("last_intent")
                context.active_device_id = data_dict.get("active_device_id")
                context.conversation_history = data_dict.get("conversation_history", [])
                context.last_track = data_dict.get("last_track")
                context.last_artist = data_dict.get("last_artist")
                context.last_album = data_dict.get("last_album")
                context.last_playlist = data_dict.get("last_playlist")
                context.last_genre = data_dict.get("last_genre")

                if data_dict.get("timestamp"):
                    context.timestamp = datetime.fromisoformat(
                        data_dict.get("timestamp")
                    )

                # Check expiry
                if context.is_expired():
                    logger.info(f"Context expired for user {user_id}, resetting")
                    context.reset()

            except Exception as e:
                logger.error(f"Failed to load context for {user_id}: {e}")
                # Return fresh context on error

        return context

    async def save_context(self, context: CommandContext) -> None:
        """Save command context to Redis.

        Args:
            context: CommandContext to save
        """
        key = f"voice_context:{context.user_id}"

        data = {
            "user_id": context.user_id,
            "last_command": context.last_command,
            "last_intent": context.last_intent,
            "active_device_id": context.active_device_id,
            "conversation_history": context.conversation_history,
            "timestamp": context.timestamp.isoformat() if context.timestamp else None,
            "last_track": context.last_track,
            "last_artist": context.last_artist,
            "last_album": context.last_album,
            "last_playlist": context.last_playlist,
            "last_genre": context.last_genre,
        }

        # Save with TTL (e.g., 1 hour to keep it around longer than the logic timeout)
        await redis_client.setex(key, 3600, json.dumps(data))

    async def update_context(
        self,
        user_id: str,
        intent: CommandIntent,
        result: Optional[CommandResult] = None,
    ) -> None:
        """Update conversation context after command execution.

        Args:
            user_id: User identifier
            intent: Executed command intent
            result: Optional command result
        """
        context = await self.get_context(user_id)

        # Update timestamp to keep context alive
        context.update_timestamp()

        # Update command history
        context.last_command = intent.raw_text
        context.last_intent = intent.intent
        context.conversation_history.append(
            {
                "command": intent.raw_text,
                "intent": intent.intent,
                "timestamp": datetime.utcnow().isoformat(),
                "success": result.success if result else None,
            }
        )

        # Keep only last 10 commands in history
        if len(context.conversation_history) > 10:
            context.conversation_history = context.conversation_history[-10:]

        # Update entity context from parameters
        if "track" in intent.parameters:
            context.last_track = intent.parameters["track"]

        if "artist" in intent.parameters:
            context.last_artist = intent.parameters["artist"]

        if "playlist" in intent.parameters:
            context.last_playlist = intent.parameters["playlist"]

        if "album" in intent.parameters:
            context.last_album = intent.parameters["album"]

        # Extract context from successful result data
        if result and result.success and result.data:
            # Update track info from result
            if "track_name" in result.data:
                context.last_track = result.data["track_name"]

            if "artist" in result.data or "artist_name" in result.data:
                context.last_artist = result.data.get("artist") or result.data.get(
                    "artist_name"
                )

            if "album" in result.data or "album_name" in result.data:
                context.last_album = result.data.get("album") or result.data.get(
                    "album_name"
                )

            if "playlist_name" in result.data:
                context.last_playlist = result.data["playlist_name"]

            # Update device context
            if "device_id" in result.data:
                context.active_device_id = result.data["device_id"]

        logger.info(
            f"Updated context for user {user_id}: "
            f"track={context.last_track}, artist={context.last_artist}, "
            f"album={context.last_album}, playlist={context.last_playlist}"
        )

        await self.save_context(context)

    async def parse_command(self, text: str, user_id: str) -> CommandIntent:
        """Parse a voice command with user context.

        Args:
            text: Raw command text
            user_id: User identifier

        Returns:
            Parsed CommandIntent
        """
        context = await self.get_context(user_id)
        intent = self.parser.parse_command(text, context)

        logger.info(
            f"Parsed command for user {user_id}: "
            f"intent={intent.intent}, confidence={intent.confidence:.2f}, "
            f"parameters={intent.parameters}"
        )

        return intent

    def generate_response(self, result: CommandResult, intent: CommandIntent) -> str:
        """Generate user-friendly response message.

        Args:
            result: Command execution result
            intent: Original command intent

        Returns:
            User-friendly response message
        """
        if not result.success:
            return self._generate_error_response(result, intent)

        return self._generate_success_response(result, intent)

    def _generate_success_response(
        self, result: CommandResult, intent: CommandIntent
    ) -> str:
        """Generate success response message.

        Args:
            result: Successful command result
            intent: Original command intent

        Returns:
            Success message
        """
        intent_type = intent.intent
        data = result.data

        # Track playback responses
        if intent_type == "play_track":
            track_name = data.get("track_name", "track")
            artist_name = data.get("artist_name", "")
            if artist_name:
                return f"Now playing '{track_name}' by {artist_name}"
            return f"Now playing '{track_name}'"

        # Playlist playback responses
        if intent_type == "play_playlist":
            playlist_name = data.get("playlist_name", "playlist")
            return f"Playing playlist '{playlist_name}'"

        # Album playback responses
        if intent_type == "play_album":
            album_name = data.get("album_name", "album")
            artist_name = data.get("artist_name", "")
            if artist_name:
                return f"Playing album '{album_name}' by {artist_name}"
            return f"Playing album '{album_name}'"

        # Artist playback responses
        if intent_type == "play_artist":
            artist_name = data.get("artist_name", "artist")
            return f"Playing music by {artist_name}"

        # Playback control responses
        if intent_type == "pause":
            return "Paused"

        if intent_type == "resume":
            return "Resumed playback"

        if intent_type == "next":
            track_name = data.get("track_name")
            if track_name:
                return f"Skipped to '{track_name}'"
            return "Skipped to next track"

        if intent_type == "previous":
            track_name = data.get("track_name")
            if track_name:
                return f"Playing '{track_name}'"
            return "Playing previous track"

        # Volume control responses
        if intent_type == "set_volume":
            level = data.get("volume", intent.parameters.get("level"))
            return f"Volume set to {level}%"

        if intent_type == "volume_up":
            return "Volume increased"

        if intent_type == "volume_down":
            return "Volume decreased"

        # Device control responses
        if intent_type == "switch_device":
            device_name = data.get("device_name", "device")
            return f"Switched to {device_name}"

        if intent_type == "list_devices":
            devices = data.get("devices", [])
            if not devices:
                return "No devices available"
            device_names = [d.get("name", "Unknown") for d in devices]
            return f"Available devices: {', '.join(device_names)}"

        # Follow-up command responses
        if intent_type == "play_another_by_artist":
            track_name = data.get("track_name", "track")
            artist_name = data.get("artist_name", data.get("artist", ""))
            if artist_name:
                return f"Playing another track by {artist_name}: '{track_name}'"
            return f"Now playing '{track_name}'"

        if intent_type == "play_more_like_this":
            track_name = data.get("track_name", "track")
            artist_name = data.get("artist_name", data.get("artist", ""))
            if artist_name:
                return f"Playing similar music: '{track_name}' by {artist_name}"
            return f"Now playing '{track_name}'"

        if intent_type == "play_from_same_album":
            album_name = data.get("album_name", "album")
            artist_name = data.get("artist_name", data.get("artist", ""))
            if artist_name:
                return f"Playing album '{album_name}' by {artist_name}"
            return f"Playing album '{album_name}'"

        # Default success message
        return result.message or "Done"

    def _generate_error_response(
        self, result: CommandResult, intent: CommandIntent
    ) -> str:
        """Generate error response message.

        Args:
            result: Failed command result
            intent: Original command intent

        Returns:
            Error message
        """
        # Use provided error message if available
        if result.message:
            return result.message

        # Generate intent-specific error messages
        intent_type = intent.intent

        if intent_type == "play_track":
            track = intent.parameters.get("track", "that track")
            return f"Couldn't find '{track}'. Try being more specific."

        if intent_type == "play_playlist":
            playlist = intent.parameters.get("playlist", "that playlist")
            return f"Couldn't find playlist '{playlist}'"

        if intent_type == "play_album":
            album = intent.parameters.get("album", "that album")
            return f"Couldn't find album '{album}'"

        if intent_type in ["pause", "resume", "next", "previous"]:
            return "No active playback found. Start playing something first."

        if intent_type in ["set_volume", "volume_up", "volume_down"]:
            return "Couldn't adjust volume. Make sure Spotify is playing."

        # Default error message
        return "Something went wrong. Please try again."

    def handle_ambiguity(self, options: list[dict], intent: CommandIntent) -> str:
        """Generate clarification message for ambiguous commands.

        Args:
            options: List of possible options to choose from
            intent: Original command intent

        Returns:
            Clarification message
        """
        if not options:
            return "I couldn't find what you're looking for."

        intent_type = intent.intent

        # For track searches
        if intent_type == "play_track":
            if len(options) == 1:
                track = options[0]
                track_name = track.get("name", "")
                artist_name = track.get("artist", "")
                return f"Did you mean '{track_name}' by {artist_name}?"

            # Multiple options
            suggestions = []
            for i, track in enumerate(options[:3], 1):  # Limit to top 3
                track_name = track.get("name", "")
                artist_name = track.get("artist", "")
                suggestions.append(f"{track_name} by {artist_name}")

            return (
                f"I found multiple matches. Did you mean: {', or '.join(suggestions)}?"
            )

        # For playlist searches
        if intent_type == "play_playlist":
            if len(options) == 1:
                playlist = options[0]
                return f"Did you mean playlist '{playlist.get('name', '')}'?"

            suggestions = [p.get("name", "") for p in options[:3]]
            return f"I found multiple playlists: {', or '.join(suggestions)}?"

        # For album searches
        if intent_type == "play_album":
            if len(options) == 1:
                album = options[0]
                album_name = album.get("name", "")
                artist_name = album.get("artist", "")
                return f"Did you mean album '{album_name}' by {artist_name}?"

            suggestions = []
            for album in options[:3]:
                album_name = album.get("name", "")
                artist_name = album.get("artist", "")
                suggestions.append(f"{album_name} by {artist_name}")

            return f"I found multiple albums: {', or '.join(suggestions)}?"

        # Default ambiguity message
        return "I found multiple matches. Can you be more specific?"

    def generate_clarification_request(self, intent: CommandIntent) -> str:
        """Generate clarification request for unclear commands.

        Args:
            intent: Command intent that needs clarification

        Returns:
            Clarification request message
        """
        intent_type = intent.intent

        if intent_type == "unknown":
            return "I didn't understand that. Try saying something like 'play Bohemian Rhapsody by Queen'"

        if intent_type == "play_track" and not intent.parameters.get("track"):
            return "What track would you like to play?"

        if intent_type == "play_playlist" and not intent.parameters.get("playlist"):
            return "Which playlist would you like to play?"

        if intent_type == "play_album" and not intent.parameters.get("album"):
            return "Which album would you like to play?"

        # Low confidence
        if intent.confidence < 0.5:
            return "I'm not sure what you want. Can you try again?"

        return "Can you repeat that?"


# Create singleton instance
voice_agent_service = VoiceAgentService()
