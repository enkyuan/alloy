"""Turn / endpoint detection policy hooks for voice STT."""

from __future__ import annotations

from enum import Enum


class TurnEndPolicy(str, Enum):
    """How end-of-user-turn is detected for a voice session."""

    MANUAL = "manual"
    ENDPOINT = "endpoint"
    HYBRID = "hybrid"


def resolve_turn_policy(*, explicit_end_signal: bool, endpoint_detected: bool) -> bool:
    """Return True when the user turn should be considered complete."""
    if explicit_end_signal:
        return True
    return endpoint_detected
