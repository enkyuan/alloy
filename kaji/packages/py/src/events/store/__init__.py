"""EventStore subpackage.

Re-exports the public surface so existing callers can keep using
`from kaji.events.store import EventStore, InMemoryEventStore`.
"""

from kaji.events.store.base import (
    AppendResult,
    EventStore,
    PurgeableEventStore,
    supports_session_purge,
)
from kaji.events.store.inmem import InMemoryEventStore

__all__ = [
    "AppendResult",
    "EventStore",
    "InMemoryEventStore",
    "PurgeableEventStore",
    "supports_session_purge",
]
