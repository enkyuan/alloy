import pytest

from agentkit.events.schemas import UserMessage
from agentkit.events.store import InMemoryEventStore


@pytest.mark.asyncio
async def test_in_memory_event_store_appends_and_sorts():
    store = InMemoryEventStore()
    await store.append(UserMessage(session_id="s1", content="b", timestamp=2.0))
    await store.append(UserMessage(session_id="s1", content="a", timestamp=1.0))

    events = await store.get_events("s1")
    user_messages = [event for event in events if isinstance(event, UserMessage)]
    assert [message.content for message in user_messages] == ["a", "b"]


@pytest.mark.asyncio
async def test_in_memory_event_store_unknown_session_returns_empty():
    store = InMemoryEventStore()
    assert await store.get_events("missing") == []
