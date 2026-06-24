"""EventStore subpackage.

Re-exports the public surface so existing callers can keep using
`from kaji.infra.events.store import EventStore, InMemoryEventStore`.
"""

from kaji.infra.events.store.base import EventStore
from kaji.infra.events.store.inmem import InMemoryEventStore

__all__ = ["EventStore", "InMemoryEventStore"]
