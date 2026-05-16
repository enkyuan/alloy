from typing import List, Protocol

from src.events.schemas import AgentKitEvent


class EventStore(Protocol):
    """Interface for a persisted event log."""

    async def append(self, event: AgentKitEvent) -> None:
        """Append an event to the store."""
        ...

    async def get_events(self, session_id: str) -> List[AgentKitEvent]:
        """Retrieve all events for a session, ordered by time."""
        ...


class InMemoryEventStore:
    """Simple in-memory event store for testing and simple deployments."""

    def __init__(self):
        self._events: dict[str, List[AgentKitEvent]] = {}

    async def append(self, event: AgentKitEvent) -> None:
        if event.session_id not in self._events:
            self._events[event.session_id] = []
        self._events[event.session_id].append(event)
        # Sort by timestamp just in case
        self._events[event.session_id].sort(key=lambda e: e.timestamp)

    async def get_events(self, session_id: str) -> List[AgentKitEvent]:
        return self._events.get(session_id, []).copy()
