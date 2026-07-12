"""Process-local coordination for mutually exclusive session turns."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Protocol
from weakref import ReferenceType, ref

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.limits import (
    ProviderCancellationContractViolation,
    TurnTimeoutError,
)
from kaji.runtime.determinism import (
    Clock,
    SYSTEM_CLOCK,
    SYSTEM_TIMER_SCHEDULER,
    TimerScheduler,
)


class TurnCoordinator(Protocol):
    """Coordinates exclusive access to a session's turn state."""

    def acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None = None,
        *,
        deadline_monotonic: float | None = None,
        clock: Clock = SYSTEM_CLOCK,
        scheduler: TimerScheduler = SYSTEM_TIMER_SCHEDULER,
    ) -> AbstractAsyncContextManager["TurnLease"]: ...

    async def quarantine(self, session_id: str) -> None: ...

    async def clear_quarantine(self, session_id: str) -> None: ...


class TurnLease(Protocol):
    """Exclusive session ownership that can move to runtime quarantine."""

    def transfer(self) -> "TurnLease": ...

    async def release(self) -> None: ...


@dataclass
class _SessionQueue:
    held: bool = False
    quarantined: bool = False
    waiters: OrderedDict[asyncio.Future[None], None] = field(
        default_factory=OrderedDict
    )
    granted_waiters: set[asyncio.Future[None]] = field(default_factory=set)


class _TurnLease(AbstractAsyncContextManager["_TurnLease"]):
    def __init__(
        self,
        coordinator: "InMemoryTurnCoordinator",
        session_id: str,
        cancellation_token: CancellationToken | None,
        deadline_monotonic: float | None,
        clock: Clock,
        scheduler: TimerScheduler,
    ) -> None:
        self._coordinator = coordinator
        self._session_id = session_id
        self._cancellation_token = cancellation_token
        self._deadline_monotonic = deadline_monotonic
        self._clock = clock
        self._scheduler = scheduler
        self._entry: _SessionQueue | None = None
        self._transferred = False

    async def __aenter__(self) -> "_TurnLease":
        self._entry = await self._coordinator._acquire(
            self._session_id,
            self._cancellation_token,
            self._deadline_monotonic,
            self._clock,
            self._scheduler,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if not self._transferred:
            await self.release()

    def transfer(self) -> "_TurnLease":
        if self._entry is None:
            raise RuntimeError("cannot transfer an inactive turn lease")
        self._transferred = True
        return self

    async def release(self) -> None:
        if self._entry is None:
            return
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
        *,
        deadline_monotonic: float | None = None,
        clock: Clock = SYSTEM_CLOCK,
        scheduler: TimerScheduler = SYSTEM_TIMER_SCHEDULER,
    ) -> AbstractAsyncContextManager[_TurnLease]:
        if not session_id:
            raise ValueError("session_id must not be empty")
        if isinstance(deadline_monotonic, bool):
            raise TypeError("deadline_monotonic must be a finite number")
        if deadline_monotonic is not None and not math.isfinite(deadline_monotonic):
            raise ValueError("deadline_monotonic must be finite")
        return _TurnLease(
            self,
            session_id,
            cancellation_token,
            deadline_monotonic,
            clock,
            scheduler,
        )

    async def _acquire(
        self,
        session_id: str,
        cancellation_token: CancellationToken | None,
        deadline_monotonic: float | None,
        clock: Clock,
        scheduler: TimerScheduler,
    ) -> _SessionQueue:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if (
            deadline_monotonic is not None
            and clock.now_monotonic() >= deadline_monotonic
        ):
            raise TurnTimeoutError(phase="queue", retryable=True, outcome="not_started")

        waiter: asyncio.Future[None] | None = None
        async with self._guard:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if (
                deadline_monotonic is not None
                and clock.now_monotonic() >= deadline_monotonic
            ):
                raise TurnTimeoutError(
                    phase="queue", retryable=True, outcome="not_started"
                )
            entry = self._entries.get(session_id)
            if entry is None:
                entry = _SessionQueue()
                self._entries[session_id] = entry
            if entry.quarantined:
                raise ProviderCancellationContractViolation()
            if not entry.held:
                entry.held = True
                return entry
            waiter = asyncio.get_running_loop().create_future()
            entry.waiters[waiter] = None

        try:
            await self._wait_for_turn(
                waiter,
                cancellation_token,
                deadline_monotonic,
                clock,
                scheduler,
            )
        except BaseException:
            await self._abandon_waiter(session_id, entry, waiter)
            raise
        if waiter is not None:
            entry.granted_waiters.discard(waiter)
        return entry

    async def quarantine(self, session_id: str) -> None:
        """Reject queued and future work while a transferred lease is active."""
        async with self._guard:
            entry = self._entries.get(session_id)
            if entry is None or not entry.held:
                raise RuntimeError("cannot quarantine a session without a held lease")
            entry.quarantined = True
            while entry.waiters:
                waiter, _ = entry.waiters.popitem(last=False)
                if not waiter.done():
                    waiter.set_exception(ProviderCancellationContractViolation())

    async def clear_quarantine(self, session_id: str) -> None:
        async with self._guard:
            entry = self._entries.get(session_id)
            if entry is not None:
                entry.quarantined = False
                if not entry.held and not entry.waiters:
                    self._entries.pop(session_id, None)

    async def _wait_for_turn(
        self,
        waiter: asyncio.Future[None],
        cancellation_token: CancellationToken | None,
        deadline_monotonic: float | None,
        clock: Clock,
        scheduler: TimerScheduler,
    ) -> None:
        if cancellation_token is None and deadline_monotonic is None:
            await waiter
            return

        cancellation_wait = (
            asyncio.create_task(cancellation_token.wait())
            if cancellation_token is not None
            else None
        )
        deadline_wait = asyncio.get_running_loop().create_future()
        timer = None
        if deadline_monotonic is not None:
            timer = scheduler.call_later(
                max(0.0, deadline_monotonic - clock.now_monotonic()),
                lambda: (
                    deadline_wait.set_result(None) if not deadline_wait.done() else None
                ),
            )
        try:
            await asyncio.wait(
                tuple(
                    item
                    for item in (waiter, cancellation_wait, deadline_wait)
                    if item is not None
                ),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if (
                deadline_monotonic is not None
                and clock.now_monotonic() >= deadline_monotonic
            ):
                raise TurnTimeoutError(
                    phase="queue", retryable=True, outcome="not_started"
                )
            await waiter
        finally:
            if timer is not None:
                timer.cancel()
            if cancellation_wait is not None:
                cancellation_wait.cancel()
                with suppress(asyncio.CancelledError):
                    await cancellation_wait
            if not deadline_wait.done():
                deadline_wait.cancel()

    async def _abandon_waiter(
        self,
        session_id: str,
        entry: _SessionQueue,
        waiter: asyncio.Future[None],
    ) -> None:
        async with self._guard:
            if waiter not in entry.waiters:
                if waiter in entry.granted_waiters:
                    entry.granted_waiters.discard(waiter)
                    self._release_locked(session_id, entry)
                return
            entry.waiters.pop(waiter)

    async def _release(self, session_id: str, entry: _SessionQueue) -> None:
        async with self._guard:
            self._release_locked(session_id, entry)

    def _release_locked(self, session_id: str, entry: _SessionQueue) -> None:
        if entry.quarantined:
            entry.held = False
            return
        while entry.waiters:
            waiter, _ = entry.waiters.popitem(last=False)
            if waiter.done():
                continue
            entry.granted_waiters.add(waiter)
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
