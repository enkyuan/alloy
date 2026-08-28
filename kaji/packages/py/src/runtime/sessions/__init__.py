"""Session management — state, store, and replay."""

import importlib
from typing import Any


_LAZY: dict[str, str] = {
    "ApprovalKey": "kaji.runtime.sessions.replay",
    "EventTimeline": "kaji.runtime.sessions.timeline",
    "EventStore": "kaji.runtime.sessions.store",
    "HistoryStore": "kaji.runtime.agents.history",
    "InMemoryEventStore": "kaji.runtime.sessions.store",
    "InMemoryHistoryStore": "kaji.runtime.agents.history",
    "InMemorySessionStore": "kaji.runtime.sessions.store",
    "SessionManager": "kaji.runtime.sessions.manager",
    "SessionProjector": "kaji.runtime.sessions.projector",
    "SessionRecord": "kaji.runtime.sessions.store",
    "SessionState": "kaji.runtime.sessions.replay",
    "SessionStore": "kaji.runtime.sessions.store",
    "apply_event": "kaji.runtime.sessions.replay",
    "replay_session": "kaji.runtime.sessions.replay",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
