"""In-memory EventStore backend.

Intended for tests and simple deployments. Events are kept in a per-session
dict and lost on process exit. Use a persistent backend in production once
one is available.
"""

from typing import List

from kaji.infra.events.schemas import KajiEvent


class InMemoryEventStore:
    """Simple in-memory event store for testing and simple deployments."""

    def __init__(self) -> None:
        self._events: dict[str, List[KajiEvent]] = {}

    async def append(self, event: KajiEvent) -> None:
        # Fast path: runtime-emitted events have monotonically increasing
        # timestamps, so the bucket stays sorted with a single ``append``.
        # Only re-sort when a caller (test fixture, replay tooling) backdates
        # the timestamp.
        bucket = self._events.get(event.session_id)
        if bucket is None:
            self._events[event.session_id] = [event]
            return
        bucket.append(event)
        if len(bucket) > 1 and bucket[-1].timestamp < bucket[-2].timestamp:
            bucket.sort(key=lambda e: e.timestamp)

    async def get_events(self, session_id: str) -> List[KajiEvent]:
        return self._events.get(session_id, []).copy()
