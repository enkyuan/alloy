"""Spotify service data models."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    message: str
    data: dict
    error: Optional[str] = None
