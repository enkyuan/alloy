"""Sequenced event journals for stable and split delivery backends."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass

from kaji.infra.events.errors import (
    EventBufferOverflowError,
    EventDeliveryError,
    EventInfrastructureError,
    EventStoreCapacityError,
)
from kaji.infra.events.protocols import EventBusProtocol
from kaji.infra.events.schemas import (
    NewKajiEvent,
    StoredKajiEvent,
    require_stored_event,
)
from kaji.infra.events.store import EventStore, InMemoryEventStore


@dataclass(eq=False, slots=True)
class _Subscriber:
    queue: asyncio.Queue[StoredKajiEvent | EventBufferOverflowError]
    last_sequence: int


class InMemoryEventJournal:
    """Stable in-process journal with atomic append and bounded fanout."""

    def __init__(
        self,
        store: EventStore | None = None,
        *,
        subscriber_queue_capacity: int = 1_024,
    ) -> None:
        if subscriber_queue_capacity < 1:
            raise ValueError("subscriber_queue_capacity must be positive")
        self.store = store if store is not None else InMemoryEventStore()
        self.subscriber_queue_capacity = subscriber_queue_capacity
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[_Subscriber]] = defaultdict(list)

    @staticmethod
    def _sequence(event: StoredKajiEvent) -> int:
        stored = require_stored_event(event)
        assert stored.sequence is not None
        return stored.sequence

    def _overflow(self, session_id: str, subscriber: _Subscriber, latest: int) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is not None and subscriber in subscribers:
            subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(session_id, None)
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(
            EventBufferOverflowError(
                last_sequence=subscriber.last_sequence,
                latest_sequence=latest,
            )
        )

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent:
        async with self._lock:
            try:
                result = await self.store.append(event)
            except EventInfrastructureError:
                raise
            except Exception as exc:
                raise EventDeliveryError(
                    phase="append",
                    event_id=event.id,
                    persisted=False,
                ) from exc

            stored = require_stored_event(result.event)
            if not result.inserted:
                return stored

            latest = self._sequence(stored)
            for subscriber in list(self._subscribers.get(stored.session_id, ())):
                if subscriber.queue.full():
                    self._overflow(stored.session_id, subscriber, latest)
                else:
                    subscriber.queue.put_nowait(stored)
            return stored

    async def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")

        subscriber = _Subscriber(
            queue=asyncio.Queue(maxsize=self.subscriber_queue_capacity),
            last_sequence=after_sequence,
        )
        async with self._lock:
            backlog = await self.store.get_events(
                session_id,
                after_sequence=after_sequence,
                limit=self.subscriber_queue_capacity + 1,
            )
            if len(backlog) > self.subscriber_queue_capacity:
                latest_sequence = await self.store.last_sequence(session_id)
                overflow = EventBufferOverflowError(
                    last_sequence=after_sequence,
                    latest_sequence=latest_sequence,
                )
            else:
                overflow = None
                self._subscribers[session_id].append(subscriber)

        if overflow is not None:
            raise overflow

        try:
            for event in backlog:
                subscriber.last_sequence = self._sequence(event)
                yield event
            while True:
                item = await subscriber.queue.get()
                if isinstance(item, EventBufferOverflowError):
                    raise item
                subscriber.last_sequence = self._sequence(item)
                yield item
        finally:
            async with self._lock:
                subscribers = self._subscribers.get(session_id)
                if subscribers is not None and subscriber in subscribers:
                    subscribers.remove(subscriber)
                    if not subscribers:
                        self._subscribers.pop(session_id, None)


class SplitEventJournal:
    """Experimental store/bus adapter with a pending-publication outbox."""

    def __init__(
        self,
        store: EventStore,
        bus: EventBusProtocol,
        *,
        subscriber_queue_capacity: int = 1_024,
        max_pending_events: int = 1_024,
    ) -> None:
        if subscriber_queue_capacity < 1 or max_pending_events < 1:
            raise ValueError("journal capacities must be positive")
        self.store = store
        self.bus = bus
        self.subscriber_queue_capacity = subscriber_queue_capacity
        self.max_pending_events = max_pending_events
        self._lock = asyncio.Lock()
        self._pending: dict[str, StoredKajiEvent] = {}

    @property
    def pending_event_ids(self) -> frozenset[str]:
        return frozenset(self._pending)

    @staticmethod
    def _sequence(event: StoredKajiEvent) -> int:
        stored = require_stored_event(event)
        assert stored.sequence is not None
        return stored.sequence

    def _ordered_pending_through(
        self,
        event: StoredKajiEvent,
    ) -> list[StoredKajiEvent]:
        sequence = self._sequence(event)
        return sorted(
            (
                pending
                for pending in self._pending.values()
                if pending.session_id == event.session_id
                and self._sequence(pending) <= sequence
            ),
            key=self._sequence,
        )

    async def _publish_pending(self, event: StoredKajiEvent) -> None:
        try:
            await self.bus.publish(event)
        except Exception as exc:
            raise EventDeliveryError(
                phase="publish",
                event_id=event.id,
                persisted=True,
            ) from exc
        self._pending.pop(event.id, None)

    async def _drain_pending_through(self, event: StoredKajiEvent) -> None:
        for pending in self._ordered_pending_through(event):
            await self._publish_pending(pending)

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent:
        async with self._lock:
            if (
                len(self._pending) >= self.max_pending_events
                and event.id not in self._pending
            ):
                raise EventStoreCapacityError(
                    event.session_id,
                    "split delivery outbox is full "
                    f"({self.max_pending_events} pending events); "
                    "retry pending delivery before appending a new event",
                )
            try:
                result = await self.store.append(event)
            except EventInfrastructureError:
                raise
            except Exception as exc:
                raise EventDeliveryError(
                    phase="append",
                    event_id=event.id,
                    persisted=False,
                ) from exc

            stored = require_stored_event(result.event)
            if not result.inserted:
                if stored.id in self._pending:
                    await self._drain_pending_through(stored)
                return stored

            has_earlier_pending = any(
                pending.session_id == stored.session_id
                and self._sequence(pending) < self._sequence(stored)
                for pending in self._pending.values()
            )
            self._pending[stored.id] = stored
            if has_earlier_pending:
                raise EventDeliveryError(
                    phase="publish",
                    event_id=stored.id,
                    persisted=True,
                )
            await self._publish_pending(stored)
            return stored

    async def retry_pending(self, event_id: str) -> StoredKajiEvent:
        async with self._lock:
            event = self._pending.get(event_id)
            if event is None:
                raise KeyError(f"no pending event {event_id!r}")
            await self._drain_pending_through(event)
            return event

    async def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")

        live: AsyncIterator[StoredKajiEvent] | None = None
        last_sequence = after_sequence
        try:
            async with self._lock:
                live = self.bus.subscribe(
                    session_id,
                    after_sequence=after_sequence,
                )
                backlog = await self.store.get_events(
                    session_id,
                    after_sequence=after_sequence,
                    limit=self.subscriber_queue_capacity + 1,
                )
                if len(backlog) > self.subscriber_queue_capacity:
                    raise EventBufferOverflowError(
                        last_sequence=after_sequence,
                        latest_sequence=await self.store.last_sequence(session_id),
                    )

            for event in backlog:
                stored = require_stored_event(event)
                assert stored.sequence is not None
                last_sequence = stored.sequence
                yield event
            async for item in live:
                stored = require_stored_event(item)
                assert stored.sequence is not None
                if stored.sequence <= last_sequence:
                    continue
                last_sequence = stored.sequence
                yield stored
        except EventBufferOverflowError as exc:
            if exc.last_sequence < last_sequence:
                raise EventBufferOverflowError(
                    last_sequence=last_sequence,
                    latest_sequence=exc.latest_sequence,
                ) from exc
            raise
        finally:
            if live is not None:
                close = getattr(live, "aclose", None)
                if close is not None:
                    await close()
