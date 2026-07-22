"""Typed failures for the stable event journal contract."""

from __future__ import annotations

from typing import Literal, TypeAlias


DurableJsonSubject: TypeAlias = Literal[
    "tool_result",
    "workflow_result",
    "event_metadata",
    "memory_document",
    "pending_tool_call",
    "event",
]
DURABLE_JSON_SUBJECTS = frozenset(
    {
        "tool_result",
        "workflow_result",
        "event_metadata",
        "memory_document",
        "pending_tool_call",
        "event",
    }
)


class EventInfrastructureError(RuntimeError):
    """Base class for machine-classifiable event infrastructure failures."""

    code: str


class InvalidDurableValueError(EventInfrastructureError):
    """An in-process value cannot be represented by the durable JSON contract."""

    code = "INVALID_DURABLE_VALUE"

    def __init__(self, subject: DurableJsonSubject) -> None:
        self.subject = subject
        super().__init__(f"invalid durable JSON value for {subject}")


class DurableJsonLimitError(EventInfrastructureError):
    """A durable JSON value exceeds its canonical UTF-8 byte budget."""

    code = "EVENT_PAYLOAD_TOO_LARGE"

    def __init__(self, subject: DurableJsonSubject, max_bytes: int) -> None:
        self.subject = subject
        self.max_bytes = max_bytes
        super().__init__(
            f"durable JSON value for {subject} exceeds {max_bytes} UTF-8 bytes"
        )


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


SessionPurgeComponent: TypeAlias = Literal[
    "event_store",
    "event_delivery",
    "tool_idempotency_ledger",
]


class SessionPurgeBusyError(EventInfrastructureError):
    code = "SESSION_PURGE_BUSY"

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(
            f"session {session_id!r} cannot be purged while work is active"
        )


class SessionPurgeUnsupportedError(EventInfrastructureError):
    code = "SESSION_PURGE_UNSUPPORTED"

    def __init__(
        self,
        session_id: str,
        component: SessionPurgeComponent = "event_store",
    ) -> None:
        self.session_id = session_id
        self.component = component
        super().__init__(
            f"session {session_id!r} cannot be purged by {component.replace('_', ' ')}"
        )


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
