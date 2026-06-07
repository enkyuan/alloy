"""EventStore protocol — the interface every persistent backend implements."""

from typing import List, Protocol

from agentkit.infra.events.schemas import AgentKitEvent


class EventStore(Protocol):
    """Interface for a persisted event log."""

    async def append(self, event: AgentKitEvent) -> None:
        """Append an event to the store."""
        ...

    async def get_events(self, session_id: str) -> List[AgentKitEvent]:
        """Retrieve all events for a session, ordered by time."""
        ...
