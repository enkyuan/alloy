"""Process-local coordination for mutually exclusive session turns."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Protocol
from weakref import ReferenceType, ref

from kaji.runtime.agents.cancellation import CancellationToken


class TurnCoordinator(Protocol):
    """Coordinates exclusive access to a session's turn state."""

    def acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None = None,
    ) -> AbstractAsyncContextManager[None]: ...


@dataclass
class _SessionQueue:
    held: bool = False
    waiters: OrderedDict[asyncio.Future[None], None] = field(
        default_factory=OrderedDict
    )


class _TurnLease(AbstractAsyncContextManager[None]):
    def __init__(
        self,
        coordinator: "InMemoryTurnCoordinator",
        session_id: str,
        cancellation_token: CancellationToken | None,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id
        self._cancellation_token = cancellation_token
        self._entry: _SessionQueue | None = None

    async def __aenter__(self) -> None:
        self._entry = await self._coordinator._acquire(
            self._session_id,
            self._cancellation_token,
        )

    async def __aexit__(self, *exc_info: object) -> None:
        if self._entry is not None:
            await self._coordinator._release(self._session_id, self._entry)
            self._entry = None


class InMemoryTurnCoordinator:
    """FIFO keyed coordinator scoped to this Python process.

    Session entries exist only while a holder or waiter is present. Callers
    that need coordination across processes must inject a distributed
    ``TurnCoordinator`` implementation instead.
    """

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._entries: Dict[str, _SessionQueue] = {}

    @property
    def entry_count(self) -> int:
        """Number of live session queues, primarily useful for diagnostics."""
        return len(self._entries)

    @property
    def waiter_count(self) -> int:
        """Number of actively linked waiters across all session queues."""
        return sum(len(entry.waiters) for entry in self._entries.values())

    def acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None = None,
    ) -> AbstractAsyncContextManager[None]:
        if not session_id:
            raise ValueError("session_id must not be empty")
        return _TurnLease(self, session_id, cancellation_token)

    async def _acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None,
    ) -> _SessionQueue:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        waiter: asyncio.Future[None] | None = None
        async with self._guard:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            entry = self._entries.get(session_id)
            if entry is None:
                entry = _SessionQueue()
                self._entries[session_id] = entry
            if not entry.held:
                entry.held = True
                return entry
            waiter = asyncio.get_running_loop().create_future()
            entry.waiters[waiter] = None

        try:
            await self._wait_for_turn(waiter, cancellation_token)
        except BaseException:
            await self._abandon_waiter(session_id, entry, waiter)
            raise
        return entry

    async def _wait_for_turn(
        self,
        waiter: asyncio.Future[None],
        cancellation_token: CancellationToken | None,
    ) -> None:
        if cancellation_token is None:
            await waiter
            return

        cancellation_wait = asyncio.create_task(cancellation_token.wait())
        try:
            await asyncio.wait(
                (waiter, cancellation_wait),
                return_when=asyncio.FIRST_COMPLETED,
            )
            cancellation_token.raise_if_cancelled()
            await waiter
        finally:
            cancellation_wait.cancel()
            with suppress(asyncio.CancelledError):
                await cancellation_wait

    async def _abandon_waiter(
        self,
        session_id: str,
        entry: _SessionQueue,
        waiter: asyncio.Future[None],
    ) -> None:
        async with self._guard:
            if waiter not in entry.waiters:
                # The waiter was already granted the lease. Hand it forward.
                if waiter.done() and not waiter.cancelled():
                    self._release_locked(session_id, entry)
                return
            entry.waiters.pop(waiter)

    async def _release(self, session_id: str, entry: _SessionQueue) -> None:
        async with self._guard:
            self._release_locked(session_id, entry)

    def _release_locked(self, session_id: str, entry: _SessionQueue) -> None:
        while entry.waiters:
            waiter, _ = entry.waiters.popitem(last=False)
            if waiter.done():
                continue
            waiter.set_result(None)
            return

        entry.held = False
        if self._entries.get(session_id) is entry:
            self._entries.pop(session_id, None)


_DEFAULT_COORDINATOR_LOCK = RLock()
_IDENTITY_WEAK_COORDINATORS: dict[
    int, tuple[ReferenceType[Any], InMemoryTurnCoordinator]
] = {}


def _discard_identity_coordinator(key: int, reference: ReferenceType[Any]) -> None:
    with _DEFAULT_COORDINATOR_LOCK:
        current = _IDENTITY_WEAK_COORDINATORS.get(key)
        if current is not None and current[0] is reference:
            _IDENTITY_WEAK_COORDINATORS.pop(key, None)


def default_coordinator_for_store(store: object) -> InMemoryTurnCoordinator:
    """Return the process-local coordinator shared by one store object.

    Store identity is tracked through weak references regardless of custom
    equality or hash behavior. Non-weak-referenceable stores must inject a
    coordinator explicitly rather than being retained by a process-global map.
    """
    with _DEFAULT_COORDINATOR_LOCK:
        key = id(store)
        weak_entry = _IDENTITY_WEAK_COORDINATORS.get(key)
        if weak_entry is not None and weak_entry[0]() is store:
            return weak_entry[1]

        coordinator = InMemoryTurnCoordinator()
        try:
            reference = ref(
                store,
                lambda dead, identity=key: _discard_identity_coordinator(
                    identity, dead
                ),
            )
        except TypeError as exc:
            raise TypeError(
                "default turn coordination requires a weak-referenceable "
                "store; inject a coordinator explicitly"
            ) from exc
        else:
            _IDENTITY_WEAK_COORDINATORS[key] = (reference, coordinator)
        return coordinator
