"""Incremental per-session projection over a sequenced event log."""

from copy import deepcopy
from typing import Any, Dict, Optional

from kaji.infra.events.schemas import StoredKajiEvent, revalidate_stored_event
from kaji.infra.events.store import EventStore
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)
from kaji.runtime.agents.context import (
    ContextBuildResult,
    ContextWindow,
)
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.sessions.context_index import ContextIndex, ContextIndexStats
from kaji.runtime.sessions.replay import SessionState, apply_event


class SessionProjector:
    """Apply each stored event once and retain the last applied cursor."""

    def __init__(
        self,
        session_id: str,
        *,
        metrics_sink: MetricsSink = NOOP_METRICS,
        context_window: ContextWindow | None = None,
    ) -> None:
        self._state = SessionState(session_id=session_id)
        self._context_index = ContextIndex(self._state, context_window)
        self.cursor = 0
        self.applied_events = 0
        self.initialized = False
        self._metrics = metrics_sink

    @property
    def session_id(self) -> str:
        return self._state.session_id

    @property
    def state(self) -> SessionState:
        """Return a detached snapshot; projection state remains privately owned."""
        return deepcopy(self._state)

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
        self._context_index.assert_projection_owned()
        message_index = apply_event(self._state, event)
        self._context_index.apply(message_index)
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
        self._context_index.seal_cold_build()
        return len(events)

    @property
    def context_index_stats(self) -> ContextIndexStats:
        """Return an immutable snapshot of internal index operation counts."""
        return self._context_index.stats

    def build_projected_context(
        self,
        prompt: SystemPrompt,
        variables: Optional[Dict[str, Any]] = None,
        *,
        window: ContextWindow | None = None,
    ) -> ContextBuildResult:
        """Build provider context from the projection-owned bounded suffix."""
        return self._context_index.suffix(
            prompt,
            variables,
            window=window,
            metrics_sink=self._metrics,
        )

    def latest_user_content(self) -> str | None:
        """Return the indexed latest user message without scanning history."""
        return self._context_index.latest_user_content()
