"""In-memory EventStore backend.

Intended for tests and simple deployments. Events are kept in a per-session
dict and lost on process exit. Use a persistent backend in production once
one is available.
"""

from typing import List

from agentkit.infra.events.schemas import AgentKitEvent


class InMemoryEventStore:
    """Simple in-memory event store for testing and simple deployments."""

    def __init__(self) -> None:
        self._events: dict[str, List[AgentKitEvent]] = {}

    async def append(self, event: AgentKitEvent) -> None:
        if event.session_id not in self._events:
            self._events[event.session_id] = []
        self._events[event.session_id].append(event)
        self._events[event.session_id].sort(key=lambda e: e.timestamp)

    async def get_events(self, session_id: str) -> List[AgentKitEvent]:
        return self._events.get(session_id, []).copy()
