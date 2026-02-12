"""Data models for the hybrid command parser service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class CommandIntent:
    """Structured parsing result for a user utterance."""

    intent: str
    parameters: dict[str, Any]
    confidence: float
    requires_clarification: bool
    raw_text: str
    alternatives: list[str] = field(default_factory=list)
    parser_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandContext:
    """Conversation context used to resolve follow-up commands."""

    user_id: str
    last_command: Optional[str] = None
    last_intent: Optional[str] = None
    active_device_id: Optional[str] = None
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    timestamp: Optional[datetime] = None
    last_track: Optional[str] = None
    last_artist: Optional[str] = None
    last_playlist: Optional[str] = None
    last_album: Optional[str] = None
    last_genre: Optional[str] = None

    CONTEXT_TIMEOUT_SECONDS: int = 300

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    def is_expired(self) -> bool:
        if self.timestamp is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        return elapsed > self.CONTEXT_TIMEOUT_SECONDS

    def reset(self) -> None:
        self.last_command = None
        self.last_intent = None
        self.conversation_history = []
        self.timestamp = datetime.now(timezone.utc)
        self.last_track = None
        self.last_artist = None
        self.last_playlist = None
        self.last_album = None
        self.last_genre = None

    def update_timestamp(self) -> None:
        self.timestamp = datetime.now(timezone.utc)
