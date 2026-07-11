from typing import cast

import pytest

from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.types import EventType
from kaji.infra.events.schemas import StoredKajiEvent, UserMessage
from kaji.infra.events.store import InMemoryEventStore
from kaji.modalities.text import TextModalityAdapter, TextSession


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


class _RawStore(InMemoryEventStore):
    def __init__(self, missing_field: str) -> None:
        super().__init__()
        self.missing_field = missing_field

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        del session_id, after_sequence, limit
        row: dict[str, object] = {
            "id": "event",
            "version": "1.0",
            "timestamp": 0,
            "type": "session.created",
            "session_id": "session",
            "sequence": 1,
        }
        row.pop(self.missing_field)
        return [cast(StoredKajiEvent, row)]


def test_text_modality_adapter_create_session():
    adapter = TextModalityAdapter()
    session = adapter.create_session(session_id="sess-1", user_id="user-1")
    assert session == {
        "session_id": "sess-1",
        "user_id": "user-1",
        "modality": "text",
    }


async def test_text_modality_adapter_open_session_sends_text_turn():
    adapter = TextModalityAdapter()
    session = adapter.open_session(session_id="sess-2", user_id="user-1")

    assert isinstance(session, TextSession)
    events = await session.send("hello")
    types = [event.type for event in events]

    assert EventType.USER_MESSAGE in types
    assert EventType.AGENT_MESSAGE_COMPLETED in types
    assert (await session.events()) == events


async def test_text_session_rejects_empty_content():
    session = TextModalityAdapter().open_session(session_id="sess-3", user_id="user-1")

    import pytest

    with pytest.raises(ValueError, match="content"):
        await session.send("  ")


async def test_text_session_events_defaults_to_a_bounded_page() -> None:
    store = _RecordingStore()
    session = TextModalityAdapter(store=store).open_session(
        session_id="sess-4",
        user_id="user-1",
    )

    assert await session.events() == []
    assert store.last_page_request == (0, 1_024)

    assert await session.events(after_sequence=10, limit=7) == []
    assert store.last_page_request == (10, 7)


@pytest.mark.parametrize("missing_field", ["id", "version", "timestamp"])
async def test_text_session_events_canonically_validate_custom_store_rows(
    missing_field: str,
) -> None:
    session = TextModalityAdapter(store=_RawStore(missing_field)).open_session(
        session_id="session",
        user_id="user",
    )

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        await session.events()

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == f"/{missing_field}"


async def test_text_session_send_returns_current_turn_after_large_history() -> None:
    store = InMemoryEventStore()
    session = TextModalityAdapter(store=store).open_session(
        session_id="sess-large",
        user_id="user-1",
    )
    for index in range(1_025):
        await store.append(UserMessage(session_id="sess-large", content=f"old-{index}"))

    events = await session.send("current")

    assert events
    assert all(event.sequence > 1_025 for event in events)
    assert any(
        isinstance(event, UserMessage) and event.content == "current"
        for event in events
    )
