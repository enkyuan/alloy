from __future__ import annotations

import pytest

from kaji.infra.events import InMemoryEventJournal, UserMessage
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents import AgentBuilder, AgentRuntime
from kaji.runtime.providers.mock import MockProvider


class _RecordingStore(InMemoryEventStore):
    def __init__(self) -> None:
        super().__init__()
        self.last_page_request: tuple[int, int | None] | None = None

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ):
        self.last_page_request = (after_sequence, limit)
        return await super().get_events(
            session_id,
            after_sequence=after_sequence,
            limit=limit,
        )


def test_builder_derives_read_store_from_injected_journal() -> None:
    store = InMemoryEventStore()
    journal = InMemoryEventJournal(store)

    runtime = AgentBuilder().provider(MockProvider(reply="ok")).build(journal=journal)

    assert runtime.journal is journal
    assert runtime.store is store


def test_builder_rejects_store_that_does_not_match_injected_journal() -> None:
    journal = InMemoryEventJournal(InMemoryEventStore())

    with pytest.raises(ValueError, match="same object as journal.store"):
        AgentBuilder().provider(MockProvider(reply="ok")).build(
            store=InMemoryEventStore(),
            journal=journal,
        )


def test_runtime_rejects_store_that_does_not_match_injected_journal() -> None:
    journal = InMemoryEventJournal(InMemoryEventStore())

    with pytest.raises(ValueError, match="same object as journal.store"):
        AgentRuntime(
            bus=None,
            store=InMemoryEventStore(),
            journal=journal,
            provider=MockProvider(reply="ok"),
        )


@pytest.mark.asyncio
async def test_builder_uses_stable_journal_and_runtime_append_path() -> None:
    runtime = AgentBuilder().provider(MockProvider(reply="ok")).build()

    assert isinstance(runtime.journal, InMemoryEventJournal)
    draft = UserMessage(session_id="seeded", content="hello")
    stored = await runtime.append_event(draft)
    duplicate = await runtime.append_event(draft.model_copy(deep=True))

    assert stored.sequence == 1
    assert duplicate == stored
    assert duplicate is not stored
    assert [event.sequence for event in await runtime.history("seeded")] == [1]


@pytest.mark.asyncio
async def test_turn_result_contains_only_persisted_cursor_events() -> None:
    runtime = AgentBuilder().provider(MockProvider(reply="ok")).build()

    first = await runtime.turn("first", session_id="session")
    second = await runtime.turn("second", session_id="session")

    assert [event.sequence for event in first.events] == list(
        range(1, len(first.events) + 1)
    )
    assert all(event.sequence is not None for event in second.events)
    last_sequence = first.events[-1].sequence
    assert last_sequence is not None
    assert second.events[0].sequence == last_sequence + 1
    page = await runtime.history(
        "session",
        after_sequence=last_sequence,
        limit=2,
    )
    assert page == second.events[:2]


@pytest.mark.asyncio
async def test_runtime_history_defaults_to_a_bounded_page() -> None:
    store = _RecordingStore()
    runtime = AgentBuilder().provider(MockProvider(reply="ok")).build(store=store)

    assert await runtime.history("session") == []
    assert store.last_page_request == (0, 1_024)
