"""Postgres advisory-lock coordination for cross-process session turns."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
import hashlib
import math
from typing import Any

from kaji.core.determinism import (
    Clock,
    SYSTEM_CLOCK,
    SYSTEM_TIMER_SCHEDULER,
    TimerScheduler,
)
from kaji.runtime.agents.cancel import CancellationToken
from kaji.runtime.agents.coordinator import TurnLease
from kaji.runtime.agents.limits import (
    ProviderCancellationContractViolation,
    TurnTimeoutError,
)


def postgres_lock_key(session_id: str) -> int:
    """Return the signed bigint advisory-lock key shared with the TypeScript SDK."""

    if not isinstance(session_id, str) or not session_id.strip():
        raise TypeError("session_id must be a non-empty string")
    return int.from_bytes(
        hashlib.sha256(session_id.encode()).digest()[:8], "big", signed=True
    )


def _get_pool() -> Any:
    try:
        from psycopg_pool import AsyncConnectionPool  # noqa: PLC0415

        return AsyncConnectionPool
    except ImportError as exc:
        raise ImportError(
            "Postgres coordination requires `pip install 'kaji[postgres]'`."
        ) from exc


class _PostgresTurnLease(AbstractAsyncContextManager["_PostgresTurnLease"]):
    def __init__(
        self,
        coordinator: "PostgresTurnCoordinator",
        session_id: str,
        key: int,
        context: Any,
        connection: Any,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id
        self._key = key
        self._context = context
        self._connection = connection
        self._released = False
        self._transferred = False

    async def __aenter__(self) -> "_PostgresTurnLease":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self._transferred:
            await self.release()

    def transfer(self) -> "_PostgresTurnLease":
        if self._released:
            raise RuntimeError("cannot transfer a released turn lease")
        self._transferred = True
        return self

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            await self._connection.execute(
                "SELECT pg_advisory_unlock(%s)", (self._key,)
            )
        finally:
            self._coordinator._held.discard(self._session_id)
            await self._context.__aexit__(None, None, None)


class PostgresTurnCoordinator:
    """Session coordinator using one reserved pooled connection per held turn.

    Advisory locks are released if the process or connection dies. They are not
    lease-fenced; deployments needing more locks than ``max_connections`` should
    move coordination to a dedicated service rather than raising this limit.
    """

    def __init__(
        self,
        dsn: str,
        *,
        max_connections: int = 10,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise TypeError("dsn must be a non-empty string")
        if not isinstance(max_connections, int) or max_connections < 1:
            raise ValueError("max_connections must be at least one")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._dsn = dsn
        self._max_connections = max_connections
        self._poll_interval_seconds = poll_interval_seconds
        self._pool: Any | None = None
        self._pool_guard = asyncio.Lock()
        self._held: set[str] = set()
        self._quarantined: set[str] = set()

    def acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None = None,
        *,
        deadline_monotonic: float | None = None,
        clock: Clock = SYSTEM_CLOCK,
        scheduler: TimerScheduler = SYSTEM_TIMER_SCHEDULER,
    ) -> AbstractAsyncContextManager[TurnLease]:
        del scheduler
        key = postgres_lock_key(session_id)
        if isinstance(deadline_monotonic, bool):
            raise TypeError("deadline_monotonic must be a finite number")
        if deadline_monotonic is not None and not math.isfinite(deadline_monotonic):
            raise ValueError("deadline_monotonic must be finite")
        return _AcquireLease(
            self, session_id, key, cancellation_token, deadline_monotonic, clock
        )

    async def quarantine(self, session_id: str) -> None:
        if session_id not in self._held:
            raise RuntimeError("cannot quarantine a session without a held lease")
        self._quarantined.add(session_id)

    async def clear_quarantine(self, session_id: str) -> None:
        self._quarantined.discard(session_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _pool_for(self) -> Any:
        async with self._pool_guard:
            if self._pool is None:
                pool_type = _get_pool()
                self._pool = pool_type(
                    self._dsn,
                    min_size=0,
                    max_size=self._max_connections,
                    open=False,
                )
                await self._pool.open(wait=True)
            return self._pool

    async def _acquire(
        self,
        session_id: str,
        key: int,
        cancellation_token: CancellationToken | None,
        deadline_monotonic: float | None,
        clock: Clock,
    ) -> _PostgresTurnLease:
        if session_id in self._quarantined:
            raise ProviderCancellationContractViolation()
        while True:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if (
                deadline_monotonic is not None
                and clock.now_monotonic() >= deadline_monotonic
            ):
                raise TurnTimeoutError(
                    phase="queue", retryable=True, outcome="not_started"
                )
            pool = await self._pool_for()
            context = pool.connection()
            connection = await context.__aenter__()
            try:
                row = await (
                    await connection.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                ).fetchone()
                if row is not None and bool(row[0]):
                    self._held.add(session_id)
                    return _PostgresTurnLease(
                        self, session_id, key, context, connection
                    )
            except BaseException:
                await context.__aexit__(None, None, None)
                raise
            await context.__aexit__(None, None, None)
            delay = self._poll_interval_seconds
            if deadline_monotonic is not None:
                delay = min(delay, max(0.0, deadline_monotonic - clock.now_monotonic()))
            if cancellation_token is None:
                await asyncio.sleep(delay)
            else:
                try:
                    await asyncio.wait_for(cancellation_token.wait(), timeout=delay)
                except TimeoutError:
                    pass
                cancellation_token.raise_if_cancelled()


class _AcquireLease(AbstractAsyncContextManager[_PostgresTurnLease]):
    def __init__(
        self,
        coordinator: PostgresTurnCoordinator,
        session_id: str,
        key: int,
        cancellation_token: CancellationToken | None,
        deadline_monotonic: float | None,
        clock: Clock,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id
        self._key = key
        self._cancellation_token = cancellation_token
        self._deadline_monotonic = deadline_monotonic
        self._clock = clock
        self._lease: _PostgresTurnLease | None = None

    async def __aenter__(self) -> _PostgresTurnLease:
        self._lease = await self._coordinator._acquire(
            self._session_id,
            self._key,
            self._cancellation_token,
            self._deadline_monotonic,
            self._clock,
        )
        return self._lease

    async def __aexit__(self, *exc_info: object) -> None:
        if self._lease is not None:
            await self._lease.__aexit__(*exc_info)
