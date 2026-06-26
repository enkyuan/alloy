"""Event timeline projection for debugging and replay UI."""

from __future__ import annotations

from typing import Sequence

from kaji.infra.events.replay import replay_session, SessionState
from kaji.infra.events.schemas import KajiEvent

__all__ = ["EventTimeline", "replay_session", "SessionState"]


class EventTimeline:
    """Ordered view of session events for inspection tools."""

    def __init__(self, events: Sequence[KajiEvent]) -> None:
        self.events = sorted(events, key=lambda event: event.timestamp)

    def event_types(self) -> list[str]:
        return [str(event.type.value) for event in self.events]

    def to_session_state(self) -> SessionState:
        if not self.events:
            raise ValueError("Cannot build session state from empty timeline")
        return replay_session(self.events)
