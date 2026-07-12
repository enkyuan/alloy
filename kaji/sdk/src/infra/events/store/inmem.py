"""Bounded in-memory event store with session-scoped commit lanes."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from kaji.infra.events.errors import EventIdConflictError, EventStoreCapacityError
from kaji.infra.events.lanes import SessionLanePool
from kaji.infra.events.schemas import (
    EventType,
    NewKajiEvent,
    StoredKajiEvent,
    revalidate_new_event,
    revalidate_stored_event,
)
from kaji.infra.events.store.base import (
    AppendResult,
    SessionEventListener,
    prepare_stored_event,
)


@dataclass(slots=True)
class _ReservationOutcome:
    result: AppendResult | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class _IdReservation:
    payload: dict[str, Any]
    done: asyncio.Future[_ReservationOutcome]


class InMemorySessionTransaction:
    """Session operations that assume the store lane is already held."""

    def __init__(self, store: InMemoryEventStore, session_id: str) -> None:
        self._store = store
        self._session_id = session_id
        self._deliveries: list[
            tuple[StoredKajiEvent, tuple[SessionEventListener, ...]]
        ] = []

    async def append_locked(self, event: NewKajiEvent) -> AppendResult:
        draft = revalidate_new_event(event)
        if draft.session_id != self._session_id:
            raise ValueError("event session_id does not match the held transaction")
        result = await self._store._append_transaction(draft)
        if result.inserted:
            listeners = tuple(self._store._listeners.get(self._session_id, ()))
            if listeners:
                self._deliveries.append((result.event, listeners))
        return result

    def get_events_locked(
        self,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        return self._store._get_events_locked(
            self._session_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def last_sequence_locked(self) -> int:
        return self._store._last_sequence_locked(self._session_id)

    def attach_listener_locked(self, listener: SessionEventListener) -> None:
        self._store._listeners[self._session_id].add(listener)

    def detach_listener_locked(self, listener: SessionEventListener) -> None:
        listeners = self._store._listeners.get(self._session_id)
        if listeners is None:
            return
        listeners.discard(listener)
        if not listeners:
            self._store._listeners.pop(self._session_id, None)

    def flush(self) -> None:
        for event, listeners in self._deliveries:
            self._store._fanout_snapshot(event, listeners)
        self._deliveries.clear()


class InMemoryEventStore:
    """A bounded append-only store serialized independently per session."""

    def __init__(
        self,
        *,
        max_sessions: int = 1_000,
        max_events_per_session: int = 10_000,
    ) -> None:
        if max_sessions < 1 or max_events_per_session < 1:
            raise ValueError("event store capacities must be positive")
        self.max_sessions = max_sessions
        self.max_events_per_session = max_events_per_session
        self._lanes = SessionLanePool()
        self._metadata_lock = asyncio.Lock()
        self._events: OrderedDict[str, list[StoredKajiEvent]] = OrderedDict()
        self._events_by_id: dict[str, StoredKajiEvent] = {}
        self._id_reservations: dict[str, _IdReservation] = {}
        self._listeners: dict[str, set[SessionEventListener]] = defaultdict(set)

    @property
    def session_transactions_enabled(self) -> bool:
        """Return false when a subclass overrides the public store boundary."""

        store_type = type(self)
        return (
            store_type.append is InMemoryEventStore.append
            and store_type.get_events is InMemoryEventStore.get_events
            and store_type.last_sequence is InMemoryEventStore.last_sequence
        )

    @property
    def active_session_lane_count(self) -> int:
        """Number of session lanes with an owner or waiter."""

        return self._lanes.active_count

    @property
    def active_id_reservation_count(self) -> int:
        """Number of event IDs awaiting append settlement."""

        return len(self._id_reservations)

    @property
    def active_listener_count(self) -> int:
        """Number of stable live listeners retained by the store."""

        return sum(len(listeners) for listeners in self._listeners.values())

    @staticmethod
    def _draft_payload(event: NewKajiEvent | StoredKajiEvent) -> dict[str, Any]:
        return event.model_dump(mode="json", exclude={"sequence"})

    @staticmethod
    def _copy_stored(event: StoredKajiEvent) -> StoredKajiEvent:
        return revalidate_stored_event(event)

    def _evict_closed_session(self) -> bool:
        for session_id, events in self._events.items():
            if (
                events
                and events[-1].type == EventType.SESSION_CLOSED
                and not self._lanes.is_active(session_id)
            ):
                removed = self._events.pop(session_id)
                for event in removed:
                    self._events_by_id.pop(event.id, None)
                return True
        return False

    async def _claim_id(
        self, draft: NewKajiEvent
    ) -> AppendResult | tuple[bool, _IdReservation]:
        payload = self._draft_payload(draft)
        async with self._metadata_lock:
            existing = self._events_by_id.get(draft.id)
            if existing is not None:
                if self._draft_payload(existing) != payload:
                    raise EventIdConflictError(draft.id)
                return AppendResult(event=self._copy_stored(existing), inserted=False)

            reservation = self._id_reservations.get(draft.id)
            if reservation is not None:
                if reservation.payload != payload:
                    raise EventIdConflictError(draft.id)
                return False, reservation

            reservation = _IdReservation(
                payload=payload,
                done=asyncio.get_running_loop().create_future(),
            )
            self._id_reservations[draft.id] = reservation
            return True, reservation

    def _finish_reservation(
        self,
        event_id: str,
        reservation: _IdReservation,
        outcome: _ReservationOutcome,
    ) -> None:
        if self._id_reservations.get(event_id) is reservation:
            self._id_reservations.pop(event_id)
        if not reservation.done.done():
            reservation.done.set_result(outcome)

    async def _insert_reserved(self, draft: NewKajiEvent) -> AppendResult:
        bucket = self._events.get(draft.session_id)
        is_new_session = bucket is None
        if bucket is None:
            bucket = []
        if len(bucket) >= self.max_events_per_session:
            raise EventStoreCapacityError(
                draft.session_id,
                f"session reached {self.max_events_per_session} events",
            )

        stored = prepare_stored_event(draft, len(bucket) + 1)
        async with self._metadata_lock:
            if is_new_session:
                if (
                    len(self._events) >= self.max_sessions
                    and not self._evict_closed_session()
                ):
                    raise EventStoreCapacityError(
                        draft.session_id,
                        f"all {self.max_sessions} session slots are active",
                    )
                self._events[draft.session_id] = bucket
            bucket.append(stored)
            self._events_by_id[stored.id] = stored
            self._events.move_to_end(stored.session_id)
        return AppendResult(event=self._copy_stored(stored), inserted=True)

    def _fanout_snapshot(
        self,
        event: StoredKajiEvent,
        listeners: tuple[SessionEventListener, ...],
    ) -> None:
        active = self._listeners.get(event.session_id)
        for listener in listeners:
            if not listener(event):
                if active is not None:
                    active.discard(listener)
        if active is not None and not active:
            self._listeners.pop(event.session_id, None)

    async def _append_transaction(self, draft: NewKajiEvent) -> AppendResult:
        claim = await self._claim_id(draft)
        if isinstance(claim, AppendResult):
            return claim
        owner, reservation = claim
        if not owner:
            outcome = await asyncio.shield(reservation.done)
            if outcome.error is not None:
                raise outcome.error
            assert outcome.result is not None
            return AppendResult(
                event=self._copy_stored(outcome.result.event),
                inserted=False,
            )

        try:
            result = await self._insert_reserved(draft)
        except BaseException as error:
            self._finish_reservation(
                draft.id,
                reservation,
                _ReservationOutcome(error=error),
            )
            raise
        self._finish_reservation(
            draft.id,
            reservation,
            _ReservationOutcome(result=result),
        )
        return result

    @asynccontextmanager
    async def session_transaction(
        self, session_id: str
    ) -> AsyncIterator[InMemorySessionTransaction]:
        transaction = InMemorySessionTransaction(self, session_id)
        try:
            async with self._lanes.hold(session_id):
                yield transaction
        finally:
            transaction.flush()

    async def append(self, event: NewKajiEvent) -> AppendResult:
        # Snapshot before waiting so caller mutation cannot alter persistence.
        draft = revalidate_new_event(event)
        async with self.session_transaction(draft.session_id) as transaction:
            return await transaction.append_locked(draft)

    def _get_events_locked(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        bucket = self._events.get(session_id)
        if bucket is None or limit == 0:
            return []
        self._events.move_to_end(session_id)
        start = min(after_sequence, len(bucket))
        stop = None if limit is None else start + limit
        return [self._copy_stored(event) for event in bucket[start:stop]]

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        async with self.session_transaction(session_id) as transaction:
            return transaction.get_events_locked(
                after_sequence=after_sequence,
                limit=limit,
            )

    def _last_sequence_locked(self, session_id: str) -> int:
        bucket = self._events.get(session_id)
        if not bucket:
            return 0
        self._events.move_to_end(session_id)
        sequence = revalidate_stored_event(bucket[-1]).sequence
        assert sequence is not None
        return sequence

    async def last_sequence(self, session_id: str) -> int:
        async with self.session_transaction(session_id) as transaction:
            return transaction.last_sequence_locked()
