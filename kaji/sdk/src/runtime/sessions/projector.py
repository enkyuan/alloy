"""Incremental per-session projection over a sequenced event log."""

from kaji.infra.events.replay import SessionState, apply_event
from kaji.infra.events.schemas import StoredKajiEvent, revalidate_stored_event
from kaji.infra.events.store import EventStore
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)


class SessionProjector:
    """Apply each stored event once and retain the last applied cursor."""

    def __init__(
        self,
        session_id: str,
        *,
        metrics_sink: MetricsSink = NOOP_METRICS,
    ) -> None:
        self.state = SessionState(session_id=session_id)
        self.cursor = 0
        self.applied_events = 0
        self.initialized = False
        self._metrics = metrics_sink

    @property
    def session_id(self) -> str:
        return self.state.session_id

    def apply(self, event: StoredKajiEvent) -> None:
        self._apply_validated(revalidate_stored_event(event))

    def _apply_validated(self, event: StoredKajiEvent) -> None:
        if event.session_id != self.session_id:
            raise ValueError("Cannot project events from mixed sessions")
        expected = self.cursor + 1
        if event.sequence != expected:
            raise ValueError(
                f"Cannot project sequence {event.sequence}; expected sequence {expected}"
            )
        apply_event(self.state, event)
        self.cursor = event.sequence
        self.applied_events += 1

    async def sync(self, store: EventStore) -> int:
        """Read and apply the suffix strictly after the cached cursor."""
        events = [
            revalidate_stored_event(event)
            for event in await store.get_events(
                self.session_id,
                after_sequence=self.cursor,
            )
        ]
        record_metric(self._metrics, "kaji.replay.input_events", len(events))
        for event in events:
            self._apply_validated(event)
        self.initialized = True
        return len(events)
