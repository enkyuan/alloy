"""Bounded in-memory event store with session-local sequence assignment."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from kaji.infra.events.errors import EventIdConflictError, EventStoreCapacityError
from kaji.infra.events.schemas import (
    EventType,
    NewKajiEvent,
    StoredKajiEvent,
    require_new_event,
    require_stored_event,
)
from kaji.infra.events.store.base import AppendResult


class InMemoryEventStore:
    """A bounded append-only store. One lock owns all sequence and ID state."""

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
        self._lock = asyncio.Lock()
        self._events: OrderedDict[str, list[StoredKajiEvent]] = OrderedDict()
        self._events_by_id: dict[str, StoredKajiEvent] = {}

    @staticmethod
    def _draft_payload(event: NewKajiEvent | StoredKajiEvent) -> dict[str, Any]:
        return event.model_dump(mode="json", exclude={"sequence"})

    @staticmethod
    def _copy_stored(event: StoredKajiEvent) -> StoredKajiEvent:
        return require_stored_event(event.model_copy(deep=True))

    def _evict_closed_session(self) -> bool:
        for session_id, events in self._events.items():
            if events and events[-1].type == EventType.SESSION_CLOSED:
                removed = self._events.pop(session_id)
                for event in removed:
                    self._events_by_id.pop(event.id, None)
                return True
        return False

    async def append(self, event: NewKajiEvent) -> AppendResult:
        # Draft models intentionally remain mutable for callers. Detach before
        # waiting on the store lock so later caller mutation cannot alter the
        # value that this append persists.
        draft = require_new_event(event.model_copy(deep=True))
        async with self._lock:
            existing = self._events_by_id.get(draft.id)
            if existing is not None:
                if self._draft_payload(existing) != self._draft_payload(draft):
                    raise EventIdConflictError(draft.id)
                return AppendResult(event=self._copy_stored(existing), inserted=False)

            bucket = self._events.get(draft.session_id)
            if bucket is None:
                if (
                    len(self._events) >= self.max_sessions
                    and not self._evict_closed_session()
                ):
                    raise EventStoreCapacityError(
                        draft.session_id,
                        f"all {self.max_sessions} session slots are active",
                    )
                bucket = []
                self._events[draft.session_id] = bucket

            if len(bucket) >= self.max_events_per_session:
                raise EventStoreCapacityError(
                    draft.session_id,
                    f"session reached {self.max_events_per_session} events",
                )

            stored = require_stored_event(
                draft.model_copy(update={"sequence": len(bucket) + 1})
            )
            bucket.append(stored)
            self._events_by_id[stored.id] = stored
            self._events.move_to_end(stored.session_id)
            return AppendResult(event=self._copy_stored(stored), inserted=True)

    async def get_events(
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
        async with self._lock:
            bucket = self._events.get(session_id)
            if bucket is None or limit == 0:
                return []
            self._events.move_to_end(session_id)
            start = min(after_sequence, len(bucket))
            stop = None if limit is None else start + limit
            return [self._copy_stored(event) for event in bucket[start:stop]]

    async def last_sequence(self, session_id: str) -> int:
        async with self._lock:
            bucket = self._events.get(session_id)
            if not bucket:
                return 0
            self._events.move_to_end(session_id)
            sequence = require_stored_event(bucket[-1]).sequence
            assert sequence is not None
            return sequence
