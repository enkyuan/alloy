"""EventStore subpackage.

Re-exports the public surface so existing callers can keep using
`from agentkit.infra.events.store import EventStore, InMemoryEventStore`.
"""

from agentkit.infra.events.store.base import EventStore
from agentkit.infra.events.store.inmem import InMemoryEventStore

__all__ = ["EventStore", "InMemoryEventStore"]
