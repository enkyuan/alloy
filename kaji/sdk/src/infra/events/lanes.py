"""Ref-counted FIFO commit lanes keyed by session ID."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


class NestedEventTransactionError(RuntimeError):
    """Raised when one task recursively enters a store transaction."""


@dataclass(slots=True)
class _Lane:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


@dataclass(slots=True)
class _TransactionMarker:
    active: bool = True


class SessionLanePool:
    """Serialize one session while allowing unrelated sessions to overlap."""

    def __init__(self) -> None:
        self._lanes: dict[str, _Lane] = {}
        self._marker: ContextVar[_TransactionMarker | None] = ContextVar(
            f"event_lane_marker_{id(self)}", default=None
        )

    @property
    def active_count(self) -> int:
        return len(self._lanes)

    def is_active(self, session_id: str) -> bool:
        return session_id in self._lanes

    def _retain(self, session_id: str) -> _Lane:
        lane = self._lanes.get(session_id)
        if lane is None:
            lane = _Lane()
            self._lanes[session_id] = lane
        lane.users += 1
        return lane

    def _release(self, session_id: str, lane: _Lane) -> None:
        lane.users -= 1
        if lane.users == 0 and self._lanes.get(session_id) is lane:
            self._lanes.pop(session_id)

    @asynccontextmanager
    async def hold(self, session_id: str) -> AsyncIterator[None]:
        inherited = self._marker.get()
        if inherited is not None and inherited.active:
            raise NestedEventTransactionError(
                "event store session transactions cannot be nested"
            )

        lane = self._retain(session_id)
        acquired = False
        try:
            await lane.lock.acquire()
            acquired = True
            marker = _TransactionMarker()
            token = self._marker.set(marker)
            try:
                yield
            finally:
                marker.active = False
                self._marker.reset(token)
        finally:
            if acquired:
                lane.lock.release()
            self._release(session_id, lane)
