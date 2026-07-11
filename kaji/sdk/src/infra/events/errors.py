"""Typed failures for the stable event journal contract."""

from __future__ import annotations

from typing import Literal


class EventInfrastructureError(RuntimeError):
    """Base class for machine-classifiable event infrastructure failures."""

    code: str


class EventSchemaIncompatibleError(EventInfrastructureError):
    """A serialized event does not satisfy the frozen wire schema."""

    code = "EVENT_SCHEMA_INCOMPATIBLE"

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"event schema is incompatible at {path}")


class EventIdConflictError(EventInfrastructureError):
    code = "EVENT_ID_CONFLICT"

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"event id {event_id!r} already exists with a different payload"
        )


class EventStoreCapacityError(EventInfrastructureError):
    code = "EVENT_STORE_CAPACITY_EXCEEDED"

    def __init__(self, session_id: str, reason: str) -> None:
        self.session_id = session_id
        self.reason = reason
        super().__init__(f"event store capacity exceeded for {session_id!r}: {reason}")


class EventBufferOverflowError(EventInfrastructureError):
    code = "EVENT_BUFFER_OVERFLOW"

    def __init__(self, *, last_sequence: int, latest_sequence: int) -> None:
        self.last_sequence = last_sequence
        self.latest_sequence = latest_sequence
        super().__init__(
            "subscriber buffer overflowed "
            f"after sequence {last_sequence}; latest sequence is {latest_sequence}"
        )


class EventDeliveryError(EventInfrastructureError):
    """An append or publication failed at a known persistence boundary."""

    def __init__(
        self,
        *,
        phase: Literal["append", "publish"],
        event_id: str,
        persisted: bool,
    ) -> None:
        self.phase = phase
        self.event_id = event_id
        self.persisted = persisted
        self.code = (
            "EVENT_APPEND_FAILED" if phase == "append" else "EVENT_PUBLISH_FAILED"
        )
        super().__init__(
            f"{self.code}: event {event_id!r} failed during {phase}; "
            f"persisted={str(persisted).lower()}"
        )
