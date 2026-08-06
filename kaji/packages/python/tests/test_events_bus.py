import asyncio

import pytest

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.errors import EventBufferOverflowError
from kaji.infra.events.schemas import UserMessage
from kaji.infra.events.store import InMemoryEventStore


async def _close(stream: object) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


async def _stored(store: InMemoryEventStore, session_id: str, content: str):
    return (
        await store.append(UserMessage(session_id=session_id, content=content))
    ).event


@pytest.mark.asyncio
async def test_in_memory_bus_is_live_only_and_does_not_duplicate_store_history() -> (
    None
):
    store = InMemoryEventStore()
    bus = InMemoryEventBus()
    old = await _stored(store, "s1", "old")
    await bus.publish(old)

    stream = bus.subscribe("s1")
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    assert not pending.done()

    live = await _stored(store, "s1", "live")
    await bus.publish(live)
    assert await pending == live
    await _close(stream)


@pytest.mark.asyncio
async def test_in_memory_bus_isolates_sessions() -> None:
    store = InMemoryEventStore()
    bus = InMemoryEventBus()
    stream = bus.subscribe("s2")
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    await bus.publish(await _stored(store, "s1", "other"))
    await asyncio.sleep(0)
    assert not pending.done()

    expected = await _stored(store, "s2", "expected")
    await bus.publish(expected)
    assert await pending == expected
    await _close(stream)


@pytest.mark.asyncio
async def test_in_memory_bus_overflow_terminates_only_lagging_subscriber() -> None:
    store = InMemoryEventStore()
    bus = InMemoryEventBus(subscriber_queue_capacity=1)
    stream = bus.subscribe("s1")
    first_task = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)

    first = await _stored(store, "s1", "one")
    await bus.publish(first)
    assert await first_task == first
    await bus.publish(await _stored(store, "s1", "two"))
    third = await _stored(store, "s1", "three")
    await bus.publish(third)

    with pytest.raises(EventBufferOverflowError) as caught:
        await anext(stream)
    assert caught.value.last_sequence == 1
    assert caught.value.latest_sequence == 3
