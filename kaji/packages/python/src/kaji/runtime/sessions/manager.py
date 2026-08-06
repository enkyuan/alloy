"""Session lifecycle coordinator."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kaji.infra.events.store import EventStore
from kaji.runtime.sessions.replay import SessionState, replay_session
from kaji.runtime.sessions.store import SessionRecord, SessionStore

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session projections over the append-only event log.

    Pass an optional ``SessionStore`` to enable ``list_active``. Without one,
    ``list_active`` returns ``[]`` (the SDK ships no durable index by default;
    that lives in kaji-serve).
    """

    def __init__(
        self, store: EventStore, session_store: Optional[SessionStore] = None
    ) -> None:
        self._store = store
        self._session_store = session_store

    async def get_state(self, session_id: str) -> SessionState:
        events = await self._store.get_events(session_id)
        if not events:
            # Session exists in the index but has no events yet (e.g. created
            # via record_session before the first event was appended).  Return
            # a minimal empty state rather than raising.
            return SessionState(session_id=session_id)
        return replay_session(events)

    async def record_session(
        self, session_id: str, user_id: str, title: str = ""
    ) -> None:
        """Register a session in the index, if a session store is configured."""
        if self._session_store is None:
            return
        await self._session_store.record_session(
            SessionRecord(session_id=session_id, user_id=user_id, title=title)
        )

    async def list_active(self, user_id: str) -> list[dict[str, Any]]:
        """List a user's sessions. Empty if no session store is configured."""
        if self._session_store is None:
            logger.debug("list_active called with no session store; returning []")
            return []
        records = await self._session_store.list_sessions(user_id)
        return [
            {
                "session_id": r.session_id,
                "user_id": r.user_id,
                "created_at": r.created_at,
                "title": r.title,
            }
            for r in records
        ]
