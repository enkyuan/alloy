"""Production composition root for Kaji's optional Postgres adapters."""

from __future__ import annotations

from kaji.backends.postgres.committer import PostgresEventCommitter
from kaji.backends.postgres.coordinator import PostgresTurnCoordinator
from kaji.backends.postgres.idempotency import PostgresToolIdempotencyLedger
from kaji.backends.postgres.store import PostgresEventStore
from kaji.events.protocols import EventJournal
from kaji.events.store import EventStore
from kaji.runtime.agents.coordinator import TurnCoordinator
from kaji.runtime.tools.idempotency import ToolIdempotencyLedger


class KajiPostgresBackend:
    """Compose the matching Postgres store, journal, ledger, and coordinator."""

    def __init__(
        self,
        dsn: str,
        *,
        max_connections: int = 10,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        store = PostgresEventStore(dsn)
        self.store: EventStore = store
        self.journal: EventJournal = PostgresEventCommitter(
            store, poll_interval=poll_interval_seconds
        )
        self.idempotency_ledger: ToolIdempotencyLedger = PostgresToolIdempotencyLedger(
            dsn, poll_interval_seconds=poll_interval_seconds
        )
        self._coordinator = PostgresTurnCoordinator(
            dsn,
            max_connections=max_connections,
            poll_interval_seconds=poll_interval_seconds,
        )
        self.coordinator: TurnCoordinator = self._coordinator

    async def close(self) -> None:
        await self._coordinator.close()


PostgresBackend = KajiPostgresBackend
