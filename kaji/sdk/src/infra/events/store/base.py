"""EventStore protocol -- the interface every persistent backend implements."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

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
