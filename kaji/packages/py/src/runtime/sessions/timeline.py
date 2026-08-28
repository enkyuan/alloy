"""Session event timeline projection for debugging and replay UI."""

from __future__ import annotations

from typing import Sequence

from kaji.infra.events.schemas import StoredKajiEvent
from kaji.runtime.sessions.replay import SessionState, replay_session

__all__ = ["EventTimeline"]


class EventTimeline:
    """Ordered view of session events for inspection tools."""

    def __init__(self, events: Sequence[StoredKajiEvent]) -> None:
        self.events = list(events)

    def event_types(self) -> list[str]:
        return [str(event.type.value) for event in self.events]

    def sequences(self) -> list[int]:
        """Expose persisted order in timeline diagnostics."""
        return [event.sequence for event in self.events]

    def to_session_state(self) -> SessionState:
        if not self.events:
            raise ValueError("Cannot build session state from empty timeline")
        return replay_session(self.events)
