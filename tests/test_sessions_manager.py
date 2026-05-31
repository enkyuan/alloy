import pytest

from agentkit.infra.events.schemas import SessionCreated, UserMessage
from agentkit.infra.events.store import InMemoryEventStore
from agentkit.runtime.sessions.manager import SessionManager


@pytest.mark.asyncio
async def test_session_manager_projects_state_from_store():
    store = InMemoryEventStore()
    await store.append(SessionCreated(session_id="s1"))
    await store.append(UserMessage(session_id="s1", content="hello"))

    manager = SessionManager(store)
    state = await manager.get_state("s1")
    assert state.session_id == "s1"
    assert state.is_active is True
    assert state.messages[-1]["content"] == "hello"


@pytest.mark.asyncio
async def test_session_manager_list_active_placeholder():
    manager = SessionManager(InMemoryEventStore())
    assert await manager.list_active("user-1") == []
