"""Structural protocols for Kaji event infrastructure.

Using ``typing.Protocol`` lets ``AgentRuntime`` and other consumers accept both
the in-memory and Redis-backed implementations without an explicit inheritance
relationship, keeping the infra-free core independent of Redis.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from kaji.infra.events.schemas import NewKajiEvent, StoredKajiEvent
from kaji.infra.events.store.base import EventStore


@runtime_checkable
class EventSubscription(Protocol):
    """A ready, explicitly closable event cursor."""

    def __aiter__(self) -> EventSubscription: ...

    async def __anext__(self) -> StoredKajiEvent: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class EventBusProtocol(Protocol):
    """Structural interface shared by :class:`~kaji.infra.events.bus.InMemoryEventBus`
    and :class:`~kaji.infra.events.bus.EventBus` (Redis-backed).

    Any object that implements ``publish`` and ``subscribe`` with these
    signatures satisfies this protocol.
    """

    async def publish(self, event: StoredKajiEvent) -> str:
        """Emit an event; return an opaque message/position ID."""
        ...

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        """Yield persisted events strictly after a sequence cursor.

        The returned iterator must either be attached synchronously before this
        method returns or be backed by a durable cursor starting at
        ``after_sequence``. A lazy, live-only iterator does not satisfy the
        contract because it can lose events before its first ``anext()``.
        """
        ...


@runtime_checkable
class EventJournal(Protocol):
    """Canonical append and gap-free subscription boundary."""

    store: EventStore

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent: ...

    async def open_subscription(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> EventSubscription:
        """Return only after backlog/live attachment is complete."""
        ...

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]: ...
