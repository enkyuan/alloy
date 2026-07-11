"""Incremental per-session projection over a sequenced event log."""

from kaji.infra.events.replay import SessionState, apply_event
from kaji.infra.events.schemas import StoredKajiEvent, require_stored_event
from kaji.infra.events.store import EventStore


class SessionProjector:
    """Apply each stored event once and retain the last applied cursor."""

    def __init__(self, session_id: str) -> None:
        self.state = SessionState(session_id=session_id)
        self.cursor = 0
        self.applied_events = 0
        self.initialized = False

    @property
    def session_id(self) -> str:
        return self.state.session_id

    def apply(self, event: StoredKajiEvent) -> None:
        stored = require_stored_event(event)
        if stored.session_id != self.session_id:
            raise ValueError("Cannot project events from mixed sessions")
        expected = self.cursor + 1
        if stored.sequence != expected:
            raise ValueError(
                f"Cannot project sequence {stored.sequence}; expected sequence {expected}"
            )
        apply_event(self.state, stored)
        self.cursor = stored.sequence
        self.applied_events += 1

    async def sync(self, store: EventStore) -> int:
        """Read and apply the suffix strictly after the cached cursor."""
        events = await store.get_events(
            self.session_id,
            after_sequence=self.cursor,
        )
        for event in events:
            self.apply(event)
        self.initialized = True
        return len(events)
