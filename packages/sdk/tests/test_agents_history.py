import pytest

from agentkit.runtime.agents.history import InMemoryHistoryStore


@pytest.mark.asyncio
async def test_history_append_and_get():
    store = InMemoryHistoryStore()
    await store.append("u1", "user", "hi", history_limit=100)
    await store.append("u1", "assistant", "hello", history_limit=100)
    assert await store.get("u1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_history_skips_consecutive_duplicates():
    store = InMemoryHistoryStore()
    await store.append("u1", "user", "same", history_limit=100)
    await store.append("u1", "user", "same", history_limit=100)
    assert len(await store.get("u1")) == 1
    # A non-consecutive repeat is allowed.
    await store.append("u1", "assistant", "x", history_limit=100)
    await store.append("u1", "user", "same", history_limit=100)
    assert len(await store.get("u1")) == 3


@pytest.mark.asyncio
async def test_history_trims_to_limit():
    store = InMemoryHistoryStore()
    for i in range(5):
        await store.append("u1", "user", f"m{i}", history_limit=3)
    history = await store.get("u1")
    assert [m["content"] for m in history] == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_history_isolates_keys():
    store = InMemoryHistoryStore()
    await store.append("u1", "user", "for-1", history_limit=100)
    assert await store.get("u2") == []


@pytest.mark.asyncio
async def test_history_get_returns_copies():
    store = InMemoryHistoryStore()
    await store.append("u1", "user", "hi", history_limit=100)
    snapshot = await store.get("u1")
    snapshot[0]["content"] = "mutated"
    # Mutating the returned list must not corrupt stored state.
    assert (await store.get("u1"))[0]["content"] == "hi"
