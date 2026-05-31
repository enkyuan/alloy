"""Event timeline projection for debugging and replay UI."""

from __future__ import annotations

from typing import Sequence

from agentkit.infra.events.replay import ReplaySession, SessionState
from agentkit.infra.events.schemas import AgentKitEvent

__all__ = ["EventTimeline", "ReplaySession", "SessionState"]


class EventTimeline:
    """Ordered view of session events for inspection tools."""

    def __init__(self, events: Sequence[AgentKitEvent]) -> None:
        self.events = sorted(events, key=lambda event: event.timestamp)

    def event_types(self) -> list[str]:
        return [str(event.type.value) for event in self.events]

    def to_session_state(self) -> SessionState:
        if not self.events:
            raise ValueError("Cannot build session state from empty timeline")
        return ReplaySession(self.events)
