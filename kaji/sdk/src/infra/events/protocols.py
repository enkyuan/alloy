"""Structural protocols for Kaji event infrastructure.

Using ``typing.Protocol`` lets ``AgentRuntime`` and other consumers accept both
the in-memory and Redis-backed implementations without an explicit inheritance
relationship, keeping the infra-free core independent of Redis.
"""

from __future__ import annotations

from typing import AsyncGenerator, Protocol, runtime_checkable

from kaji.infra.events.schemas import KajiEvent


@runtime_checkable
class EventBusProtocol(Protocol):
    """Structural interface shared by :class:`~kaji.infra.events.bus.InMemoryEventBus`
    and :class:`~kaji.infra.events.bus.EventBus` (Redis-backed).

    Any object that implements ``publish`` and ``subscribe`` with these
    signatures satisfies this protocol.
    """

    async def publish(self, event: KajiEvent) -> str:
        """Emit an event; return an opaque message/position ID."""
        ...

    async def subscribe(self, session_id: str) -> AsyncGenerator[KajiEvent, None]:
        """Yield events for *session_id*, starting from backlog then live."""
        ...
        # This unreachable yield makes the return type an AsyncGenerator,
        # satisfying Protocol static-analysis requirements.
        yield  # type: ignore[misc]
