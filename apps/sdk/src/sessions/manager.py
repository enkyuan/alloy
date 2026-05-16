"""Session lifecycle coordinator."""

from __future__ import annotations

from typing import Any

from src.sessions.replay import ReplaySession
from src.sessions.state import SessionState
from src.events.store import EventStore


class SessionManager:
    """Manages session projections over the append-only event log."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    async def get_state(self, session_id: str) -> SessionState:
        events = await self._store.get_events(session_id)
        return ReplaySession(events)

    async def list_active(self, _user_id: str) -> list[dict[str, Any]]:
        """Placeholder until session persistence is wired."""
        return []
