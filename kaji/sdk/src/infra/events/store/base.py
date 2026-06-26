"""EventStore protocol — the interface every persistent backend implements."""

from typing import List, Protocol

from kaji.infra.events.schemas import KajiEvent


class EventStore(Protocol):
    """Interface for a persisted event log."""

    async def append(self, event: KajiEvent) -> None:
        """Append an event to the store."""
        ...

    async def get_events(self, session_id: str) -> List[KajiEvent]:
        """Retrieve all events for a session, ordered by time."""
        ...
