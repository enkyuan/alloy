import pytest

from agentkit.infra.events.schemas import SessionCreated, UserMessage
from agentkit.infra.events.store import InMemoryEventStore
from agentkit.runtime.sessions.manager import SessionManager
from agentkit.runtime.sessions.store import InMemorySessionStore, SessionRecord


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
async def test_list_active_empty_without_store():
    manager = SessionManager(InMemoryEventStore())
    assert await manager.list_active("user-1") == []


@pytest.mark.asyncio
async def test_list_active_returns_recorded_sessions():
    sessions = InMemorySessionStore()
    await sessions.record_session(SessionRecord(session_id="s1", user_id="u1"))
    mgr = SessionManager(InMemoryEventStore(), session_store=sessions)
    active = await mgr.list_active("u1")
    assert len(active) == 1
    assert active[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_recording_then_listing_round_trips():
    sessions = InMemorySessionStore()
    mgr = SessionManager(InMemoryEventStore(), session_store=sessions)
    await mgr.record_session("s9", "u1", title="chat")
    active = await mgr.list_active("u1")
    assert [s["session_id"] for s in active] == ["s9"]
    assert active[0]["title"] == "chat"


@pytest.mark.asyncio
async def test_record_session_noop_without_store():
    # Recording with no store configured must not raise.
    mgr = SessionManager(InMemoryEventStore())
    await mgr.record_session("s1", "u1")
    assert await mgr.list_active("u1") == []
