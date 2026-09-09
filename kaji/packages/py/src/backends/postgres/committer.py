"""Polling commit/subscription seam for :mod:`kaji.backends.postgres`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from kaji.backends.postgres.store import PostgresEventStore
from kaji.events.schemas import NewKajiEvent, StoredKajiEvent
from kaji.events.store import EventStore


class _PostgresSubscription:
    def __init__(
        self,
        store: EventStore,
        session_id: str,
        after_sequence: int,
        page_size: int,
        poll_interval: float,
    ) -> None:
        self._store = store
        self._session_id = session_id
        self._cursor = after_sequence
        self._page_size = page_size
        self._poll_interval = poll_interval
        self._backlog: list[StoredKajiEvent] = []
        self._closed = False

    def __aiter__(self) -> _PostgresSubscription:
        return self

    async def __anext__(self) -> StoredKajiEvent:
        while not self._closed:
            if self._backlog:
                event = self._backlog.pop(0)
                self._cursor = event.sequence or self._cursor
                return event
            self._backlog = await self._store.get_events(
                self._session_id,
                after_sequence=self._cursor,
                limit=self._page_size,
            )
            if not self._backlog:
                await asyncio.sleep(self._poll_interval)
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self._closed = True


class PostgresEventCommitter:
    """Commit to Postgres and subscribe through its durable sequence cursor."""

    def __init__(
        self,
        store: PostgresEventStore,
        *,
        poll_interval: float = 0.05,
        page_size: int = 100,
    ) -> None:
        if poll_interval <= 0 or page_size < 1:
            raise ValueError(
                "poll_interval must be positive and page_size must be at least one"
            )
        self.store: EventStore = store
        self._poll_interval = poll_interval
        self._page_size = page_size

    async def commit(self, event: NewKajiEvent) -> StoredKajiEvent:
        return (await self.store.append(event)).event

    async def open_subscription(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> _PostgresSubscription:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        return _PostgresSubscription(
            self.store,
            session_id,
            after_sequence,
            self._page_size,
            self._poll_interval,
        )

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
