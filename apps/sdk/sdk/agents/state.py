from sdk.events.replay import ReplaySession, SessionState
from sdk.events.store import EventStore


class SessionStateManager:
    """Manages retrieving and projecting the active state of a conversation."""

    def __init__(self, store: EventStore):
        self.store = store

    async def load_state(self, session_id: str) -> SessionState:
        """Reconstruct the session state from the append-only event log."""
        events = await self.store.get_events(session_id)
        if not events:
            return SessionState(session_id=session_id)
        return ReplaySession(events)
