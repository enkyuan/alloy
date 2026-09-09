"""Backend composition boundary shared by in-memory and durable adapters."""

from __future__ import annotations

from typing import Protocol

from kaji.events.protocols import EventJournal
from kaji.events.store import EventStore
from kaji.runtime.agents.coordinator import TurnCoordinator
from kaji.runtime.tools.idempotency import ToolIdempotencyLedger


class KajiBackend(Protocol):
    """The four durable seams a Kaji runtime composes."""

    @property
    def store(self) -> EventStore: ...

    @property
    def journal(self) -> EventJournal: ...

    @property
    def idempotency_ledger(self) -> ToolIdempotencyLedger: ...

    @property
    def coordinator(self) -> TurnCoordinator: ...
