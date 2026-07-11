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
from kaji.infra.events.protocols import EventBusProtocol, EventSubscription
from kaji.infra.events.schemas import (
    NewKajiEvent,
    StoredKajiEvent,
    require_stored_event,
    revalidate_new_event,
    revalidate_stored_event,
)
from kaji.infra.events.store import EventStore, InMemoryEventStore
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)


@dataclass(eq=False, slots=True)
class _Subscriber:
    queue: asyncio.Queue[StoredKajiEvent | EventBufferOverflowError]
    last_sequence: int


class _InMemoryJournalSubscription:
    """Ready subscription returned after the journal's atomic handshake."""

    def __init__(
        self,
        journal: InMemoryEventJournal,
        session_id: str,
        subscriber: _Subscriber,
        backlog: list[StoredKajiEvent],
    ) -> None:
        self._journal = journal
        self._session_id = session_id
        self._subscriber = subscriber
        self._backlog = backlog
        self._backlog_index = 0
        self._closed = False

    def __aiter__(self) -> _InMemoryJournalSubscription:
        return self

    async def __anext__(self) -> StoredKajiEvent:
        if self._closed:
            raise StopAsyncIteration
        if self._backlog_index < len(self._backlog):
            event = self._backlog[self._backlog_index]
            self._backlog_index += 1
        else:
            item = await self._subscriber.queue.get()
            if isinstance(item, EventBufferOverflowError):
                self._closed = True
                raise item
            event = item
        self._subscriber.last_sequence = self._journal._sequence(event)
        return event

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._journal._remove_subscriber(
            self._session_id,
            self._subscriber,
        )


class InMemoryEventJournal:
    """Stable in-process journal with atomic append and bounded fanout."""

    def __init__(
        self,
        store: EventStore | None = None,
        *,
        subscriber_queue_capacity: int = 1_024,
        metrics_sink: MetricsSink = NOOP_METRICS,
    ) -> None:
        if subscriber_queue_capacity < 1:
            raise ValueError("subscriber_queue_capacity must be positive")
        self.store = store if store is not None else InMemoryEventStore()
        self.subscriber_queue_capacity = subscriber_queue_capacity
        self._metrics = metrics_sink
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, list[_Subscriber]] = defaultdict(list)

    @staticmethod
    def _sequence(event: StoredKajiEvent) -> int:
        stored = require_stored_event(event)
        assert stored.sequence is not None
        return stored.sequence

    def _overflow(self, session_id: str, subscriber: _Subscriber, latest: int) -> None:
        record_metric(
            self._metrics,
            "kaji.subscriber.overflow",
            1,
            stage="overflow",
        )
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
        event = revalidate_new_event(event)
        async with self._lock:
            try:
                result = await self.store.append(event)
            except EventInfrastructureError:
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="append",
                )
                raise
            except Exception as exc:
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="append",
                )
                raise EventDeliveryError(
                    phase="append",
                    event_id=event.id,
                    persisted=False,
                ) from exc

            stored = revalidate_stored_event(result.event)
            if not result.inserted:
                return stored

            latest = self._sequence(stored)
            for subscriber in list(self._subscribers.get(stored.session_id, ())):
                if subscriber.queue.full():
                    self._overflow(stored.session_id, subscriber, latest)
                else:
                    subscriber.queue.put_nowait(stored)
                    record_metric(
                        self._metrics,
                        "kaji.subscriber.lag_events",
                        subscriber.queue.qsize(),
                    )
            return stored

    async def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[StoredKajiEvent]:
        subscription = await self.open_subscription(
            session_id,
            after_sequence=after_sequence,
        )
        try:
            async for event in subscription:
                yield event
        finally:
            await subscription.aclose()

    async def open_subscription(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> EventSubscription:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")

        subscriber = _Subscriber(
            queue=asyncio.Queue(maxsize=self.subscriber_queue_capacity),
            last_sequence=after_sequence,
        )
        async with self._lock:
            backlog = [
                revalidate_stored_event(event)
                for event in await self.store.get_events(
                    session_id,
                    after_sequence=after_sequence,
                    limit=self.subscriber_queue_capacity + 1,
                )
            ]
            record_metric(
                self._metrics,
                "kaji.subscriber.lag_events",
                len(backlog),
            )
            if len(backlog) > self.subscriber_queue_capacity:
                record_metric(
                    self._metrics,
                    "kaji.subscriber.overflow",
                    1,
                    stage="lag",
                )
                latest_sequence = await self.store.last_sequence(session_id)
                overflow = EventBufferOverflowError(
                    last_sequence=after_sequence,
                    latest_sequence=latest_sequence,
                )
            else:
                self._subscribers[session_id].append(subscriber)
                return _InMemoryJournalSubscription(
                    self,
                    session_id,
                    subscriber,
                    backlog,
                )
        raise overflow

    async def _remove_subscriber(
        self,
        session_id: str,
        subscriber: _Subscriber,
    ) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(session_id)
            if subscribers is not None and subscriber in subscribers:
                subscribers.remove(subscriber)
                if not subscribers:
                    self._subscribers.pop(session_id, None)


class _SplitJournalSubscription:
    """Merged backlog/live cursor with explicit, idempotent close."""

    def __init__(
        self,
        live: EventSubscription,
        backlog: list[StoredKajiEvent],
        after_sequence: int,
    ) -> None:
        self._live = live
        self._backlog = backlog
        self._backlog_index = 0
        self._last_sequence = after_sequence
        self._closed = False

    def __aiter__(self) -> _SplitJournalSubscription:
        return self

    async def __anext__(self) -> StoredKajiEvent:
        if self._closed:
            raise StopAsyncIteration
        while True:
            if self._backlog_index < len(self._backlog):
                stored = require_stored_event(self._backlog[self._backlog_index])
                self._backlog_index += 1
            else:
                try:
                    candidate = await anext(self._live)
                    stored = revalidate_stored_event(candidate)
                except BaseException as error:
                    try:
                        await self.aclose()
                    except BaseException:
                        # Cleanup must not replace the ingress or cancellation error.
                        pass
                    if (
                        isinstance(error, EventBufferOverflowError)
                        and error.last_sequence < self._last_sequence
                    ):
                        raise EventBufferOverflowError(
                            last_sequence=self._last_sequence,
                            latest_sequence=error.latest_sequence,
                        ) from error
                    raise
            assert stored.sequence is not None
            if stored.sequence <= self._last_sequence:
                continue
            self._last_sequence = stored.sequence
            return stored

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._live.aclose()


class SplitEventJournal:
    """Experimental store/bus adapter with a pending-publication outbox."""

    def __init__(
        self,
        store: EventStore,
        bus: EventBusProtocol,
        *,
        subscriber_queue_capacity: int = 1_024,
        max_pending_events: int = 1_024,
        metrics_sink: MetricsSink = NOOP_METRICS,
    ) -> None:
        if subscriber_queue_capacity < 1 or max_pending_events < 1:
            raise ValueError("journal capacities must be positive")
        self.store = store
        self.bus = bus
        self.subscriber_queue_capacity = subscriber_queue_capacity
        self.max_pending_events = max_pending_events
        self._metrics = metrics_sink
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
            record_metric(
                self._metrics,
                "kaji.journal.failures",
                1,
                stage="publish",
            )
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
        event = revalidate_new_event(event)
        async with self._lock:
            if (
                len(self._pending) >= self.max_pending_events
                and event.id not in self._pending
            ):
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="append",
                )
                raise EventStoreCapacityError(
                    event.session_id,
                    "split delivery outbox is full "
                    f"({self.max_pending_events} pending events); "
                    "retry pending delivery before appending a new event",
                )
            try:
                result = await self.store.append(event)
            except EventInfrastructureError:
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="append",
                )
                raise
            except Exception as exc:
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="append",
                )
                raise EventDeliveryError(
                    phase="append",
                    event_id=event.id,
                    persisted=False,
                ) from exc

            stored = revalidate_stored_event(result.event)
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
                record_metric(
                    self._metrics,
                    "kaji.journal.failures",
                    1,
                    stage="publish",
                )
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
        subscription = await self.open_subscription(
            session_id,
            after_sequence=after_sequence,
        )
        try:
            async for event in subscription:
                yield event
        finally:
            await subscription.aclose()

    async def open_subscription(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> EventSubscription:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")

        live: EventSubscription | None = None
        try:
            async with self._lock:
                candidate = self.bus.subscribe(
                    session_id, after_sequence=after_sequence
                )
                if not isinstance(candidate, EventSubscription):
                    raise TypeError("event subscriptions must implement aclose()")
                live = candidate
                backlog = [
                    revalidate_stored_event(event)
                    for event in await self.store.get_events(
                        session_id,
                        after_sequence=after_sequence,
                        limit=self.subscriber_queue_capacity + 1,
                    )
                ]
                record_metric(
                    self._metrics,
                    "kaji.subscriber.lag_events",
                    len(backlog),
                )
                if len(backlog) > self.subscriber_queue_capacity:
                    record_metric(
                        self._metrics,
                        "kaji.subscriber.overflow",
                        1,
                        stage="lag",
                    )
                    raise EventBufferOverflowError(
                        last_sequence=after_sequence,
                        latest_sequence=await self.store.last_sequence(session_id),
                    )

            return _SplitJournalSubscription(live, backlog, after_sequence)
        except BaseException:
            if live is not None:
                await live.aclose()
            raise
