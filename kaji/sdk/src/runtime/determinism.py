"""Injectable identifiers and clocks for deterministic runtime execution."""

from __future__ import annotations

from dataclasses import dataclass
import time
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


SYSTEM_ID_FACTORY = SystemIdFactory()
SYSTEM_CLOCK = SystemClock()


__all__ = [
    "Clock",
    "IdFactory",
    "IdScope",
    "SYSTEM_CLOCK",
    "SYSTEM_ID_FACTORY",
    "SystemClock",
    "SystemIdFactory",
]
