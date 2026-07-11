import asyncio

import pytest

from kaji.infra.events.errors import EventIdConflictError, EventStoreCapacityError
from kaji.infra.events.schemas import SessionClosed, UserMessage
from kaji.infra.events.store import InMemoryEventStore


@pytest.mark.asyncio
async def test_append_order_wins_over_equal_and_backdated_timestamps() -> None:
    store = InMemoryEventStore()
    first = await store.append(
        UserMessage(session_id="s1", content="first", timestamp=2.0)
    )
    second = await store.append(
        UserMessage(session_id="s1", content="second", timestamp=2.0)
    )
    third = await store.append(
        UserMessage(session_id="s1", content="third", timestamp=1.0)
    )

    assert [first.event.sequence, second.event.sequence, third.event.sequence] == [
        1,
        2,
        3,
    ]
    events = await store.get_events("s1")
    assert [event.content for event in events if isinstance(event, UserMessage)] == [
        "first",
        "second",
        "third",
    ]


@pytest.mark.asyncio
async def test_concurrent_appends_assign_contiguous_session_sequences() -> None:
    store = InMemoryEventStore()
    results = await asyncio.gather(
        *(
            store.append(UserMessage(session_id="s1", content=str(index)))
            for index in range(50)
        )
    )

    assert sorted(result.event.sequence for result in results) == list(range(1, 51))
    assert await store.last_sequence("s1") == 50


@pytest.mark.asyncio
async def test_duplicate_id_is_idempotent_but_conflicting_payload_fails() -> None:
    store = InMemoryEventStore()
    event = UserMessage(id="event-1", session_id="s1", content="same")

    inserted = await store.append(event)
    duplicate = await store.append(event.model_copy(deep=True))

    assert inserted.inserted is True
    assert duplicate.inserted is False
    assert duplicate.event is inserted.event
    assert await store.last_sequence("s1") == 1

    with pytest.raises(EventIdConflictError) as caught:
        await store.append(
            UserMessage(id="event-1", session_id="s1", content="different")
        )
    assert caught.value.code == "EVENT_ID_CONFLICT"


@pytest.mark.asyncio
async def test_cursor_is_exclusive_and_limit_is_exact() -> None:
    store = InMemoryEventStore()
    for index in range(5):
        await store.append(UserMessage(session_id="s1", content=str(index)))

    page = await store.get_events("s1", after_sequence=2, limit=2)
    assert [event.sequence for event in page] == [3, 4]
    assert await store.get_events("s1", after_sequence=5) == []
    assert await store.get_events("s1", limit=0) == []


@pytest.mark.asyncio
async def test_store_bounds_never_silently_truncate_active_history() -> None:
    store = InMemoryEventStore(max_sessions=1, max_events_per_session=1)
    await store.append(UserMessage(session_id="active", content="one"))

    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="active", content="two"))
    with pytest.raises(EventStoreCapacityError):
        await store.append(UserMessage(session_id="other", content="one"))

    assert [event.sequence for event in await store.get_events("active")] == [1]


@pytest.mark.asyncio
async def test_new_session_evicts_only_the_least_recently_used_closed_session() -> None:
    store = InMemoryEventStore(max_sessions=2)
    await store.append(UserMessage(session_id="closed", content="one"))
    await store.append(SessionClosed(session_id="closed"))
    await store.append(UserMessage(session_id="active", content="one"))

    inserted = await store.append(UserMessage(session_id="new", content="one"))

    assert inserted.event.sequence == 1
    assert await store.get_events("closed") == []
    assert await store.last_sequence("active") == 1


@pytest.mark.asyncio
async def test_unknown_session_returns_empty_and_zero_cursor() -> None:
    store = InMemoryEventStore()
    assert await store.get_events("missing") == []
    assert await store.last_sequence("missing") == 0
