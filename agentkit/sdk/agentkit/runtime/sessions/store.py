"""Session stores.

Two distinct concerns live here:

- ``EventStore`` / ``InMemoryEventStore`` (re-exported from ``infra.events``):
  the append-only event log for ONE session.
- ``SessionStore`` / ``InMemorySessionStore`` / ``SessionRecord``: a
  cross-session index keyed by user. ``EventStore`` has no such index, so it
  cannot list a user's sessions; this is the separate, optional protocol for
  that. Keeping it separate means the infra-free ``InMemoryEventStore`` does not
  have to maintain a user->session map it never needs.

The bundled ``InMemorySessionStore`` is process-local. A durable backend
(Postgres in agentkit-serve) implements the same protocol later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Protocol

from agentkit.infra.events.store import EventStore, InMemoryEventStore

__all__ = [
    "EventStore",
    "InMemoryEventStore",
    "SessionRecord",
    "SessionStore",
    "InMemorySessionStore",
]


@dataclass
class SessionRecord:
    """A row in the session index."""

    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    title: str = ""


class SessionStore(Protocol):
    """Cross-session index, keyed by user."""

    async def record_session(self, record: SessionRecord) -> None:
        ...

    async def list_sessions(self, user_id: str) -> List[SessionRecord]:
        ...


class InMemorySessionStore:
    """Process-local session index. Lost on restart."""

    def __init__(self) -> None:
        self._by_user: Dict[str, Dict[str, SessionRecord]] = {}

    async def record_session(self, record: SessionRecord) -> None:
        bucket = self._by_user.setdefault(record.user_id, {})
        bucket.setdefault(record.session_id, record)  # idempotent on session_id

    async def list_sessions(self, user_id: str) -> List[SessionRecord]:
        bucket = self._by_user.get(user_id, {})
        return sorted(bucket.values(), key=lambda r: r.created_at, reverse=True)
