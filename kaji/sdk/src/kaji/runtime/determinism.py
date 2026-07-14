"""Injectable identifiers and clocks for deterministic runtime execution."""

from __future__ import annotations

from dataclasses import dataclass
import time
from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable
import uuid


IdScope = Literal[
    "event",
    "session",
    "turn",
    "request",
    "trace",
    "tool_call",
]


@runtime_checkable
class IdFactory(Protocol):
    """Produce one identifier for the requested semantic scope."""

    def next(self, scope: IdScope) -> str: ...


@runtime_checkable
class Clock(Protocol):
    """Provide wall and monotonic time without coupling callers to globals."""

    def now_wall_seconds(self) -> float: ...

    def now_monotonic(self) -> float: ...


@runtime_checkable
class ScheduledCallback(Protocol):
    """Cancellation handle for one scheduled callback."""

    def cancel(self) -> None: ...


@runtime_checkable
class TimerScheduler(Protocol):
    """Minimal one-shot timer seam used by deadline races."""

    def call_later(
        self, delay_seconds: float, callback: Callable[[], None]
    ) -> ScheduledCallback: ...


@dataclass(frozen=True, slots=True)
class SystemIdFactory:
    """Production UUID factory preserving the existing event/non-event forms."""

    def next(self, scope: IdScope) -> str:
        value = uuid.uuid4()
        return str(value) if scope == "event" else value.hex


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production clock backed by the standard library."""

    def now_wall_seconds(self) -> float:
        return time.time()

    def now_monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True, slots=True)
class AsyncioTimerScheduler:
    """Production timer scheduler backed by the active asyncio loop."""

    def call_later(
        self, delay_seconds: float, callback: Callable[[], None]
    ) -> ScheduledCallback:
        import asyncio  # noqa: PLC0415

        return asyncio.get_running_loop().call_later(max(0.0, delay_seconds), callback)


SYSTEM_ID_FACTORY = SystemIdFactory()
SYSTEM_CLOCK = SystemClock()
SYSTEM_TIMER_SCHEDULER = AsyncioTimerScheduler()


__all__ = [
    "Clock",
    "AsyncioTimerScheduler",
    "IdFactory",
    "IdScope",
    "SYSTEM_CLOCK",
    "SYSTEM_ID_FACTORY",
    "SYSTEM_TIMER_SCHEDULER",
    "ScheduledCallback",
    "SystemClock",
    "SystemIdFactory",
    "TimerScheduler",
]
