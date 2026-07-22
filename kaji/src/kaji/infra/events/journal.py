"""Sequenced event journals for stable and split delivery backends."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from kaji.infra.events.errors import (
    EventBufferOverflowError,
    EventDeliveryError,
    EventInfrastructureError,
    EventStoreCapacityError,
)
from kaji.infra.events.session_lifecycle import (
    SessionPurgeAuthorization,
    authorized_session_teardown,
    register_purge_blocker,
    store_session_operation,
    supports_authorized_listener_teardown,
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
from kaji.infra.events.store.base import (
    EventStoreSession,
    SessionEventListener,
    SessionTransactionalEventStore,
)
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)


@dataclass(eq=False, slots=True)
class _Subscriber:
    queue: asyncio.Queue[
        StoredKajiEvent | EventBufferOverflowError | _SubscriptionClosed
    ]
    last_sequence: int
    listener: SessionEventListener | None = None
    closed: bool = False


@dataclass(frozen=True, slots=True)
class _SubscriptionClosed:
    pass


_SUBSCRIPTION_CLOSED = _SubscriptionClosed()


@dataclass(slots=True)
class _PendingSlot:
    active: bool


@dataclass(eq=False, slots=True)
class _SubscriptionCreation:
    active: bool = True
    orphaned: bool = False
    teardown: Callable[[], Awaitable[None]] | None = None
    cleanup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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
        self._detached = False
        self._detach_lock = asyncio.Lock()

    def __aiter__(self) -> _InMemoryJournalSubscription:
        return self

    async def __anext__(self) -> StoredKajiEvent:
        if self._closed or self._subscriber.closed:
            self._closed = True
            raise StopAsyncIteration
        if self._backlog_index < len(self._backlog):
            event = self._backlog[self._backlog_index]
            self._backlog_index += 1
        else:
            item = await self._subscriber.queue.get()
            if isinstance(item, _SubscriptionClosed):
                self._closed = True
                raise StopAsyncIteration
            if isinstance(item, EventBufferOverflowError):
                self._closed = True
                raise item
            event = item
        self._subscriber.last_sequence = self._journal._sequence(event)
        return event

    async def aclose(self) -> None:
        self._closed = True
        async with self._detach_lock:
            if self._detached:
                return
            if not self._subscriber.closed:
                await self._journal._remove_subscriber(
                    self._session_id,
                    self._subscriber,
                )
            self._detached = True


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
        self._transactional_store = (
            self.store
            if isinstance(self.store, SessionTransactionalEventStore)
            and self.store.session_transactions_enabled
            else None
        )

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

    def _deliver(self, subscriber: _Subscriber, event: StoredKajiEvent) -> bool:
        latest = self._sequence(event)
        if subscriber.queue.full():
            self._overflow(event.session_id, subscriber, latest)
            return False
        subscriber.queue.put_nowait(event)
        record_metric(
            self._metrics,
            "kaji.subscriber.lag_events",
            subscriber.queue.qsize(),
        )
        return True

    async def _commit_with(
        self,
        event: NewKajiEvent,
        transaction: EventStoreSession | None,
    ) -> StoredKajiEvent:
        try:
            result = (
                await transaction.append_locked(event)
                if transaction is not None
                else await self.store.append(event)
            )
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

        stored = (
            require_stored_event(result.event)
            if transaction is not None
            else revalidate_stored_event(result.event)
        )
        if result.inserted and transaction is None:
            for subscriber in list(self._subscribers.get(stored.session_id, ())):
                self._deliver(subscriber, stored)
        return stored

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent:
        event = revalidate_new_event(event)
        if self._transactional_store is not None:
            async with self._transactional_store.session_transaction(
                event.session_id
            ) as transaction:
                return await self._commit_with(event, transaction)
        async with self._lock:
            return await self._commit_with(event, None)

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

        with store_session_operation(self.store, session_id):
            subscriber = _Subscriber(
                queue=asyncio.Queue(maxsize=self.subscriber_queue_capacity),
                last_sequence=after_sequence,
            )
            if self._transactional_store is not None:
                async with self._transactional_store.session_transaction(
                    session_id
                ) as transaction:
                    backlog = [
                        revalidate_stored_event(event)
                        for event in transaction.get_events_locked(
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
                            latest_sequence=transaction.last_sequence_locked(),
                        )
                    subscriber.listener = lambda event: self._deliver(subscriber, event)
                    transaction.attach_listener_locked(subscriber.listener)
                    self._subscribers[session_id].append(subscriber)
                    return _InMemoryJournalSubscription(
                        self,
                        session_id,
                        subscriber,
                        backlog,
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
                    raise EventBufferOverflowError(
                        last_sequence=after_sequence,
                        latest_sequence=await self.store.last_sequence(session_id),
                    )
                self._subscribers[session_id].append(subscriber)
                return _InMemoryJournalSubscription(
                    self,
                    session_id,
                    subscriber,
                    backlog,
                )

    async def _remove_subscriber(
        self,
        session_id: str,
        subscriber: _Subscriber,
    ) -> None:
        if self._transactional_store is not None and subscriber.listener is not None:
            async with self._transactional_store.session_transaction(
                session_id
            ) as transaction:
                transaction.detach_listener_locked(subscriber.listener)
            self._close_subscriber(session_id, subscriber)
            return
        async with self._lock:
            self._close_subscriber(session_id, subscriber)

    def _close_subscriber(self, session_id: str, subscriber: _Subscriber) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is not None and subscriber in subscribers:
            subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(session_id, None)
        subscriber.listener = None
        subscriber.closed = True
        while not subscriber.queue.empty():
            subscriber.queue.get_nowait()
        subscriber.queue.put_nowait(_SUBSCRIPTION_CLOSED)

    async def close_session_subscriptions(
        self,
        session_id: str,
        authorization: SessionPurgeAuthorization,
    ) -> None:
        """Terminate one retained generation and detach every raw listener."""
        subscribers = tuple(self._subscribers.get(session_id, ()))
        listeners = tuple(
            subscriber.listener
            for subscriber in subscribers
            if subscriber.listener is not None
        )
        if listeners:
            if not supports_authorized_listener_teardown(self.store):
                raise TypeError("event store cannot detach listeners during purge")
            await self.store._detach_listeners_authorized(
                session_id,
                listeners,
                authorization,
            )
        else:
            with authorized_session_teardown(self.store, session_id, authorization):
                pass
        for subscriber in subscribers:
            self._close_subscriber(session_id, subscriber)


class _SplitJournalSubscription:
    """Merged backlog/live cursor with explicit, idempotent close."""

    def __init__(
        self,
        live: EventSubscription,
        backlog: list[StoredKajiEvent],
        after_sequence: int,
        on_close: Callable[[_SplitJournalSubscription], None],
    ) -> None:
        self._live = live
        self._backlog = backlog
        self._backlog_index = 0
        self._last_sequence = after_sequence
        self._closed = False
        self._detached = False
        self._unregistered = False
        self._close_lock = asyncio.Lock()
        self._on_close = on_close

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
        self._closed = True
        async with self._close_lock:
            if not self._detached:
                await self._live.aclose()
                self._detached = True
            if not self._unregistered:
                self._on_close(self)
                self._unregistered = True


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
        self._pending_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._pending: dict[str, StoredKajiEvent] = {}
        self._pending_reservations = 0
        self._subscription_creations: set[_SubscriptionCreation] = set()
        self._active_subscriptions: set[_SplitJournalSubscription] = set()
        self._closed = False
        self._transactional_store = (
            self.store
            if isinstance(self.store, SessionTransactionalEventStore)
            and self.store.session_transactions_enabled
            else None
        )
        self._unregister_purge_blocker = register_purge_blocker(self.store, self)

    @property
    def session_purge_component(self) -> Literal["event_delivery"]:
        return "event_delivery"

    async def close(self) -> None:
        async with self._close_lock:
            async with self._pending_lock:
                if self._closed:
                    return
                orphaned = tuple(
                    creation
                    for creation in self._subscription_creations
                    if creation.orphaned
                )

            cleanup_errors: list[BaseException] = []
            for creation in orphaned:
                try:
                    await self._cleanup_subscription_creation(creation)
                except BaseException as error:
                    cleanup_errors.append(error)
            if cleanup_errors:
                raise cleanup_errors[0]

            async with self._pending_lock:
                if self._pending or self._pending_reservations:
                    raise RuntimeError(
                        "split event journal cannot close with pending delivery work"
                    )
                if self._subscription_creations or self._active_subscriptions:
                    raise RuntimeError(
                        "split event journal cannot close with active subscription work"
                    )
                self._unregister_purge_blocker()
                self._closed = True

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
        async with self._pending_lock:
            self._pending.pop(event.id, None)

    async def _drain_pending_through(self, event: StoredKajiEvent) -> None:
        for pending in self._ordered_pending_through(event):
            await self._publish_pending(pending)

    async def _reserve_pending_slot(self, event: NewKajiEvent) -> _PendingSlot:
        async with self._pending_lock:
            if self._closed:
                raise RuntimeError("split event journal is closed")
            if event.id in self._pending:
                return _PendingSlot(active=False)
            if (
                len(self._pending) + self._pending_reservations
                >= self.max_pending_events
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
            self._pending_reservations += 1
            return _PendingSlot(active=True)

    async def _reserve_subscription_creation(self) -> _SubscriptionCreation:
        async with self._pending_lock:
            if self._closed:
                raise RuntimeError("split event journal is closed")
            creation = _SubscriptionCreation()
            self._subscription_creations.add(creation)
            return creation

    def _release_subscription_creation(
        self,
        creation: _SubscriptionCreation,
    ) -> None:
        if creation.active:
            self._subscription_creations.discard(creation)
            creation.active = False
            creation.orphaned = False
            creation.teardown = None

    def _retain_subscription_creation(
        self,
        creation: _SubscriptionCreation,
        teardown: Callable[[], Awaitable[None]] | None,
    ) -> None:
        creation.teardown = teardown
        creation.orphaned = True
        if not creation.active:
            creation.active = True
            self._subscription_creations.add(creation)

    async def _cleanup_subscription_creation(
        self,
        creation: _SubscriptionCreation,
    ) -> None:
        async with creation.cleanup_lock:
            if not creation.active or not creation.orphaned:
                return
            teardown = creation.teardown
            if teardown is None:
                return
            await teardown()
            self._release_subscription_creation(creation)

    async def _activate_subscription(
        self,
        creation: _SubscriptionCreation,
        subscription: _SplitJournalSubscription,
    ) -> None:
        async with self._pending_lock:
            self._active_subscriptions.add(subscription)
            self._release_subscription_creation(creation)

    def _unregister_subscription(
        self,
        subscription: _SplitJournalSubscription,
    ) -> None:
        self._active_subscriptions.discard(subscription)

    async def _release_pending_slot(self, slot: _PendingSlot) -> None:
        if not slot.active:
            return
        async with self._pending_lock:
            if slot.active:
                self._pending_reservations -= 1
                slot.active = False

    async def _promote_pending_slot(
        self,
        slot: _PendingSlot,
        event: StoredKajiEvent,
    ) -> None:
        async with self._pending_lock:
            self._pending[event.id] = event
            if slot.active:
                self._pending_reservations -= 1
                slot.active = False

    async def _commit_with(
        self,
        event: NewKajiEvent,
        slot: _PendingSlot,
        transaction: EventStoreSession | None,
    ) -> StoredKajiEvent:
        try:
            result = (
                await transaction.append_locked(event)
                if transaction is not None
                else await self.store.append(event)
            )
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

        stored = (
            require_stored_event(result.event)
            if transaction is not None
            else revalidate_stored_event(result.event)
        )
        if not result.inserted:
            if stored.id in self._pending:
                await self._drain_pending_through(stored)
            return stored

        has_earlier_pending = any(
            pending.session_id == stored.session_id
            and self._sequence(pending) < self._sequence(stored)
            for pending in self._pending.values()
        )
        await self._promote_pending_slot(slot, stored)
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

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent:
        if self._closed:
            raise RuntimeError("split event journal is closed")
        event = revalidate_new_event(event)
        slot = await self._reserve_pending_slot(event)
        try:
            if self._transactional_store is not None:
                async with self._transactional_store.session_transaction(
                    event.session_id
                ) as transaction:
                    return await self._commit_with(event, slot, transaction)
            async with self._lock:
                return await self._commit_with(event, slot, None)
        finally:
            await self._release_pending_slot(slot)

    async def retry_pending(self, event_id: str) -> StoredKajiEvent:
        async with self._pending_lock:
            if self._closed:
                raise RuntimeError("split event journal is closed")
            candidate = self._pending.get(event_id)
        if candidate is None:
            raise KeyError(f"no pending event {event_id!r}")
        if self._transactional_store is not None:
            async with self._transactional_store.session_transaction(
                candidate.session_id
            ):
                event = self._pending.get(event_id)
                if event is None:
                    raise KeyError(f"no pending event {event_id!r}")
                await self._drain_pending_through(event)
                return event
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
        creation = await self._reserve_subscription_creation()
        candidate_acquired = False
        live: EventSubscription | None = None
        subscription: _SplitJournalSubscription | None = None
        try:
            if after_sequence < 0:
                raise ValueError("after_sequence must be non-negative")
            if self._transactional_store is not None:
                async with self._transactional_store.session_transaction(
                    session_id
                ) as transaction:
                    candidate = self.bus.subscribe(
                        session_id, after_sequence=after_sequence
                    )
                    candidate_acquired = True
                    close_candidate = getattr(candidate, "aclose", None)
                    if callable(close_candidate):
                        creation.teardown = close_candidate
                    if not isinstance(candidate, EventSubscription):
                        raise TypeError("event subscriptions must implement aclose()")
                    live = candidate
                    backlog = [
                        revalidate_stored_event(event)
                        for event in transaction.get_events_locked(
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
                            latest_sequence=transaction.last_sequence_locked(),
                        )
                subscription = _SplitJournalSubscription(
                    live,
                    backlog,
                    after_sequence,
                    self._unregister_subscription,
                )
                creation.teardown = subscription.aclose
                await self._activate_subscription(creation, subscription)
                return subscription
            async with self._lock:
                candidate = self.bus.subscribe(
                    session_id, after_sequence=after_sequence
                )
                candidate_acquired = True
                close_candidate = getattr(candidate, "aclose", None)
                if callable(close_candidate):
                    creation.teardown = close_candidate
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

            subscription = _SplitJournalSubscription(
                live,
                backlog,
                after_sequence,
                self._unregister_subscription,
            )
            creation.teardown = subscription.aclose
            await self._activate_subscription(creation, subscription)
            return subscription
        except BaseException:
            teardown = (
                subscription.aclose if subscription is not None else creation.teardown
            )
            if not candidate_acquired:
                self._release_subscription_creation(creation)
            else:
                self._retain_subscription_creation(creation, teardown)
                if teardown is not None:
                    try:
                        await self._cleanup_subscription_creation(creation)
                    except BaseException:
                        # Preserve the setup/cancellation error; close() owns retries.
                        pass
            raise
