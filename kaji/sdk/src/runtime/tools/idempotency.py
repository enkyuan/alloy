"""Bounded, exact-key idempotency for tool execution."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import math
import time
from typing import Any, Callable, Literal, Protocol
import uuid
from weakref import WeakKeyDictionary

from kaji.infra.events.errors import DurableJsonSubject
from kaji.infra.events.json import durable_json_snapshot
from kaji.infra.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES


_DEFAULT_MAX_ENTRIES = 10_000
_DEFAULT_COMPLETED_TTL_SECONDS = 24 * 60 * 60


class IdempotencyCapacityExceeded(RuntimeError):
    """The ledger cannot accept another claim without evicting active state."""


class IdempotencyConflictError(RuntimeError):
    """An exact call key was reused for a different invocation."""


@dataclass(frozen=True, slots=True)
class ToolIdempotencyFailure:
    """Stable failure fields retained for waiters and unknown tombstones."""

    error: str
    error_code: str
    retryable: bool
    outcome: Literal["not_started", "failed", "unknown"]
    subject: DurableJsonSubject | None = None


@dataclass(frozen=True, slots=True)
class ToolIdempotencyResolution:
    """Detached result delivered to an owner replay or concurrent waiter."""

    result: Any | None = None
    failure: ToolIdempotencyFailure | None = None


@dataclass(frozen=True, slots=True)
class ToolIdempotencyClaim:
    """Atomic claim result returned by :class:`ToolIdempotencyLedger`."""

    kind: Literal["owner", "waiter", "completed", "unknown"]
    session_id: str
    tool_call_id: str
    claim_token: str
    resolution: ToolIdempotencyResolution | None = None


class ToolIdempotencyLedger(Protocol):
    """Replaceable persistence boundary for exact tool-call idempotency.

    Claim tokens fence one running generation and contain no process-local
    synchronization state. ``wait`` must observe a terminal transition even
    when it committed before the wait began, and must cooperate with task
    cancellation. ``is_started`` is a linearizable persistence read; the
    controller bounds it and treats an unavailable answer conservatively.
    """

    async def claim(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> ToolIdempotencyClaim: ...

    async def complete(self, claim: ToolIdempotencyClaim, result: Any) -> None: ...

    async def wait(self, claim: ToolIdempotencyClaim) -> ToolIdempotencyResolution: ...

    async def is_started(self, claim: ToolIdempotencyClaim) -> bool: ...

    async def mark_started(self, claim: ToolIdempotencyClaim) -> None: ...

    async def retryable_failure(
        self,
        claim: ToolIdempotencyClaim,
        failure: ToolIdempotencyFailure,
    ) -> None: ...

    async def unknown_outcome(
        self,
        claim: ToolIdempotencyClaim,
        failure: ToolIdempotencyFailure,
    ) -> None: ...

    async def release_completed(self, session_id: str) -> int: ...


@dataclass(slots=True)
class _WaitState:
    future: asyncio.Future[ToolIdempotencyResolution]
    started: bool = False


class _InMemoryClaimToken(str):
    __slots__ = ("__weakref__",)


@dataclass(slots=True)
class _LedgerEntry:
    session_id: str
    tool_call_id: str
    fingerprint: str
    state: Literal["running", "completed", "unknown"]
    token: _InMemoryClaimToken
    wait_state: _WaitState
    result: Any | None = None
    failure: ToolIdempotencyFailure | None = None
    completed_at: float | None = None
    last_accessed: float | None = None


def _copy_resolution(
    resolution: ToolIdempotencyResolution,
) -> ToolIdempotencyResolution:
    return ToolIdempotencyResolution(
        result=durable_json_snapshot(
            resolution.result,
            subject="tool_result",
            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
        ),
        failure=resolution.failure,
    )


def _fingerprint(tool_name: str, tool_args: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(
            [tool_name, tool_args],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TypeError("tool arguments must be JSON serializable") from error
    return hashlib.sha256(encoded).hexdigest()


class InMemoryToolIdempotencyLedger:
    """Bounded async ledger with completed-result TTL/LRU eviction.

    Running claims and unknown-outcome tombstones are never evicted implicitly.
    Applications that need restart-safe idempotency can inject a durable
    implementation of :class:`ToolIdempotencyLedger`.
    """

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        completed_ttl_seconds: float = _DEFAULT_COMPLETED_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise TypeError("max_entries must be a positive integer")
        if max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        if isinstance(completed_ttl_seconds, bool) or not isinstance(
            completed_ttl_seconds, (int, float)
        ):
            raise TypeError("completed_ttl_seconds must be positive")
        if (
            not math.isfinite(float(completed_ttl_seconds))
            or completed_ttl_seconds <= 0
        ):
            raise ValueError("completed_ttl_seconds must be positive")
        self._max_entries = max_entries
        self._completed_ttl_seconds = float(completed_ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[str, _LedgerEntry] = OrderedDict()
        self._wait_states: WeakKeyDictionary[_InMemoryClaimToken, _WaitState] = (
            WeakKeyDictionary()
        )
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._entries)

    async def claim(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> ToolIdempotencyClaim:
        key = f"{session_id}:{tool_call_id}"
        fingerprint = _fingerprint(tool_name, tool_args)
        async with self._lock:
            now = self._clock()
            self._expire_completed(now)
            entry = self._entries.get(key)
            if entry is not None:
                if (
                    entry.session_id != session_id
                    or entry.tool_call_id != tool_call_id
                    or entry.fingerprint != fingerprint
                ):
                    raise IdempotencyConflictError(
                        "tool call idempotency key conflicts with an existing invocation"
                    )
                if entry.state == "running":
                    return ToolIdempotencyClaim(
                        kind="waiter",
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        claim_token=entry.token,
                    )
                if entry.state == "completed":
                    entry.last_accessed = now
                    self._entries.move_to_end(key)
                    return ToolIdempotencyClaim(
                        kind="completed",
                        session_id=session_id,
                        tool_call_id=tool_call_id,
                        claim_token=entry.token,
                        resolution=ToolIdempotencyResolution(
                            result=durable_json_snapshot(
                                entry.result,
                                subject="tool_result",
                                max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
                            )
                        ),
                    )
                return ToolIdempotencyClaim(
                    kind="unknown",
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    claim_token=entry.token,
                    resolution=ToolIdempotencyResolution(failure=entry.failure),
                )

            self._make_capacity()
            token = _InMemoryClaimToken(uuid.uuid4().hex)
            wait_state = _WaitState(
                future=asyncio.get_running_loop().create_future(),
            )
            self._wait_states[token] = wait_state
            self._entries[key] = _LedgerEntry(
                session_id=session_id,
                tool_call_id=tool_call_id,
                fingerprint=fingerprint,
                state="running",
                token=token,
                wait_state=wait_state,
            )
            return ToolIdempotencyClaim(
                kind="owner",
                session_id=session_id,
                tool_call_id=tool_call_id,
                claim_token=token,
            )

    async def wait(self, claim: ToolIdempotencyClaim) -> ToolIdempotencyResolution:
        """Wait without allowing waiter cancellation to cancel owner state."""
        if claim.kind != "waiter":
            if claim.resolution is None:
                raise RuntimeError("only a waiter claim can be awaited")
            return _copy_resolution(claim.resolution)
        state = self._wait_state(claim)
        return _copy_resolution(await asyncio.shield(state.future))

    async def is_started(self, claim: ToolIdempotencyClaim) -> bool:
        """Read the owner start boundary behind the persistence seam."""
        return self._wait_state(claim).started

    async def mark_started(self, claim: ToolIdempotencyClaim) -> None:
        async with self._lock:
            entry = self._owner_entry(claim)
            entry.wait_state.started = True

    async def complete(self, claim: ToolIdempotencyClaim, result: Any) -> None:
        detached = durable_json_snapshot(
            result,
            subject="tool_result",
            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
        )
        waiter_result = durable_json_snapshot(
            detached,
            subject="tool_result",
            max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES,
        )
        async with self._lock:
            entry = self._owner_entry(claim)
            now = self._clock()
            entry.state = "completed"
            entry.result = detached
            entry.completed_at = now
            entry.last_accessed = now
            resolution = ToolIdempotencyResolution(result=waiter_result)
            if not entry.wait_state.future.done():
                entry.wait_state.future.set_result(resolution)
            self._entries.move_to_end(self._claim_key(claim))

    async def retryable_failure(
        self,
        claim: ToolIdempotencyClaim,
        failure: ToolIdempotencyFailure,
    ) -> None:
        async with self._lock:
            entry = self._owner_entry(claim)
            if not entry.wait_state.future.done():
                entry.wait_state.future.set_result(
                    ToolIdempotencyResolution(failure=failure)
                )
            self._entries.pop(self._claim_key(claim), None)

    async def unknown_outcome(
        self,
        claim: ToolIdempotencyClaim,
        failure: ToolIdempotencyFailure,
    ) -> None:
        async with self._lock:
            entry = self._owner_entry(claim)
            entry.state = "unknown"
            entry.failure = failure
            if not entry.wait_state.future.done():
                entry.wait_state.future.set_result(
                    ToolIdempotencyResolution(failure=failure)
                )

    async def release_completed(self, session_id: str) -> int:
        async with self._lock:
            keys = [
                key
                for key, entry in self._entries.items()
                if entry.session_id == session_id and entry.state == "completed"
            ]
            for key in keys:
                self._entries.pop(key, None)
            return len(keys)

    def _owner_entry(self, claim: ToolIdempotencyClaim) -> _LedgerEntry:
        if claim.kind != "owner":
            raise ValueError("ledger transition requires an owner claim")
        entry = self._entries.get(self._claim_key(claim))
        if (
            entry is None
            or entry.state != "running"
            or entry.token is not claim.claim_token
            or entry.session_id != claim.session_id
            or entry.tool_call_id != claim.tool_call_id
        ):
            raise RuntimeError("idempotency claim is no longer running")
        return entry

    def _wait_state(self, claim: ToolIdempotencyClaim) -> _WaitState:
        token = claim.claim_token
        if not isinstance(token, _InMemoryClaimToken):
            raise ValueError("claim token does not belong to this ledger")
        state = self._wait_states.get(token)
        if state is None:
            raise RuntimeError("idempotency claim state is no longer available")
        return state

    @staticmethod
    def _claim_key(claim: ToolIdempotencyClaim) -> str:
        return f"{claim.session_id}:{claim.tool_call_id}"

    def _expire_completed(self, now: float) -> None:
        expired = [
            key
            for key, entry in self._entries.items()
            if entry.state == "completed"
            and entry.completed_at is not None
            and now - entry.completed_at >= self._completed_ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)

    def _make_capacity(self) -> None:
        while len(self._entries) >= self._max_entries:
            completed_key = next(
                (
                    key
                    for key, entry in self._entries.items()
                    if entry.state == "completed"
                ),
                None,
            )
            if completed_key is None:
                raise IdempotencyCapacityExceeded(
                    "tool idempotency ledger capacity exhausted"
                )
            self._entries.pop(completed_key)


# Pre-beta compatibility helpers. They are deliberately local and separate
# from workflow idempotency; runtime execution uses the exact call-id ledger.
def build_tool_idempotency_key(
    *, session_id: str, tool_name: str, tool_args: dict[str, Any]
) -> str:
    return _fingerprint(f"{session_id}:{tool_name}", tool_args)[:32]


class ToolIdempotencyGuard:
    """Legacy synchronous argument-hash guard; prefer the async ledger."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def should_execute(
        self, *, session_id: str, tool_name: str, tool_args: dict[str, Any]
    ) -> bool:
        key = build_tool_idempotency_key(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True
