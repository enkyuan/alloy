"""Text modality adapter for non-voice chat sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from kaji.infra.events.schemas import StoredKajiEvent, revalidate_stored_event
from kaji.infra.events.store import EventStore, InMemoryEventStore
from kaji.runtime.agents.context import ToolInvocation
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.providers.registry import get_provider


@dataclass(frozen=True)
class TextSessionConfig:
    session_id: str
    user_id: str
    modality: str = "text"


@dataclass
class TextSession:
    """A text chat session bound to an ``AgentRuntime``."""

    config: TextSessionConfig
    runtime: AgentRuntime
    store: EventStore

    async def send(self, content: str) -> list[StoredKajiEvent]:
        """Send text through the runtime and return only this turn's events."""
        if not content.strip():
            raise ValueError("content must not be empty")
        result = await self.runtime.turn(content, session_id=self.config.session_id)
        return result.events

    async def events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 1_024,
    ) -> list[StoredKajiEvent]:
        """Return a bounded cursor page of events for this text session."""
        return [
            revalidate_stored_event(event)
            for event in await self.store.get_events(
                self.config.session_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        ]


class TextModalityAdapter:
    """Facade for text-based session setup and runtime wiring."""

    modality = "text"

    def __init__(
        self,
        runtime: Optional[AgentRuntime] = None,
        store: Optional[EventStore] = None,
    ) -> None:
        self._runtime = runtime
        self._store = store

    def create_session(self, session_id: str, user_id: str) -> dict[str, Any]:
        """Return a serializable text-session descriptor."""
        config = TextSessionConfig(session_id=session_id, user_id=user_id)
        return {
            "session_id": config.session_id,
            "user_id": config.user_id,
            "modality": config.modality,
        }

    def open_session(self, session_id: str, user_id: str) -> TextSession:
        """Create a text session that can send messages through a runtime.

        If no runtime is supplied, a zero-network runtime is assembled with
        in-memory events and the built-in mock provider.
        """
        config = TextSessionConfig(session_id=session_id, user_id=user_id)
        store = self._store or InMemoryEventStore()
        runtime = self._runtime or _default_runtime(store)
        return TextSession(config=config, runtime=runtime, store=store)


def _default_runtime(store: EventStore) -> AgentRuntime:
    async def _missing_tool_executor(
        invocation: ToolInvocation,
    ) -> dict[str, Any]:
        raise ValueError(f"No tool executor configured for {invocation.name!r}")

    return AgentRuntime(
        store=store,
        provider=get_provider("mock"),
        planner=ToolPlanner(executor=_missing_tool_executor),
    )
