"""EventStore protocol -- the interface every persistent backend implements."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, TypeGuard, runtime_checkable

from kaji.infra.events.schemas import (
    NewKajiEvent,
    StoredKajiEvent,
    revalidate_stored_event_for_append,
)


@dataclass(frozen=True, slots=True)
class AppendResult:
    event: StoredKajiEvent
    inserted: bool


def prepare_stored_event(event: NewKajiEvent, sequence: int) -> StoredKajiEvent:
    """Build and validate the stored candidate before a backend mutates state."""

    payload = event.model_dump(mode="python")
    payload["sequence"] = sequence
    return revalidate_stored_event_for_append(payload)


@runtime_checkable
class EventStore(Protocol):
    """Interface for a persisted event log."""

    async def append(self, event: NewKajiEvent) -> AppendResult:
        """Append a draft once and return its persisted representation."""
        ...

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        """Return events strictly after the cursor in append order."""
        ...

    async def last_sequence(self, session_id: str) -> int:
        """Return the latest session-local sequence, or zero when absent."""
        ...


@runtime_checkable
class PurgeableEventStore(EventStore, Protocol):
    """Public one-argument destructive teardown capability."""

    async def purge_session(self, session_id: str) -> bool: ...


def supports_session_purge(store: EventStore) -> TypeGuard[PurgeableEventStore]:
    return callable(getattr(store, "purge_session", None))


SessionEventListener = Callable[[StoredKajiEvent], bool]


class EventStoreSession(Protocol):
    """Operations valid only while a store-owned session lane is held."""

    async def append_locked(self, event: NewKajiEvent) -> AppendResult: ...

    def get_events_locked(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]: ...

    def last_sequence_locked(self) -> int: ...

    def attach_listener_locked(self, listener: SessionEventListener) -> None: ...

    def detach_listener_locked(self, listener: SessionEventListener) -> None: ...


@runtime_checkable
class SessionTransactionalEventStore(EventStore, Protocol):
    """Internal capability for atomic session-scoped append and fanout."""

    @property
    def session_transactions_enabled(self) -> bool: ...

    def session_transaction(
        self, session_id: str
    ) -> AbstractAsyncContextManager[EventStoreSession]: ...
