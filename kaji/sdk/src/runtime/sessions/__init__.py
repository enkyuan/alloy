"""Session management — state, store, and replay."""

from kaji.runtime.agents.history import HistoryStore, InMemoryHistoryStore
from kaji.runtime.sessions.manager import SessionManager
from kaji.runtime.sessions.projector import SessionProjector
from kaji.runtime.sessions.replay import replay_legacy_session, replay_session
from kaji.runtime.sessions.state import SessionState
from kaji.runtime.sessions.store import (
    EventStore,
    InMemoryEventStore,
    InMemorySessionStore,
    SessionRecord,
    SessionStore,
)

__all__ = [
    "EventStore",
    "HistoryStore",
    "InMemoryEventStore",
    "InMemoryHistoryStore",
    "InMemorySessionStore",
    "replay_session",
    "replay_legacy_session",
    "SessionManager",
    "SessionProjector",
    "SessionRecord",
    "SessionState",
    "SessionStore",
]
