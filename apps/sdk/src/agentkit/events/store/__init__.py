"""EventStore subpackage.

Re-exports the public surface so existing callers can keep using
`from agentkit.events.store import EventStore, InMemoryEventStore`.
"""

from agentkit.events.store.base import EventStore
from agentkit.events.store.inmem import InMemoryEventStore

__all__ = ["EventStore", "InMemoryEventStore"]
