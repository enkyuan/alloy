import pytest

from agentkit.runtime.sessions.store import InMemorySessionStore, SessionRecord


@pytest.mark.asyncio
async def test_record_and_list_for_user():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    sessions = await store.list_sessions("u1")
    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"


@pytest.mark.asyncio
async def test_users_are_isolated():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    await store.record_session(SessionRecord(session_id="s2", user_id="u2"))
    assert len(await store.list_sessions("u1")) == 1
    assert len(await store.list_sessions("u2")) == 1
    assert await store.list_sessions("u3") == []


@pytest.mark.asyncio
async def test_recording_same_session_is_idempotent():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    assert len(await store.list_sessions("u1")) == 1


@pytest.mark.asyncio
async def test_list_sorted_newest_first():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="old", user_id="u1", created_at=1.0))
    await store.record_session(SessionRecord(session_id="new", user_id="u1", created_at=2.0))
    ids = [r.session_id for r in await store.list_sessions("u1")]
    assert ids == ["new", "old"]
