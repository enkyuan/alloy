from kaji.infra.events.types import EventType
from kaji.modalities.text import TextModalityAdapter, TextSession


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
