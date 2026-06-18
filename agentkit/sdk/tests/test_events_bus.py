import asyncio

import pytest

from agentkit.infra.events.bus import InMemoryEventBus
from agentkit.infra.events.schemas import UserMessage


@pytest.mark.asyncio
async def test_in_memory_bus_replays_backlog_to_late_subscriber():
    bus = InMemoryEventBus()
    await bus.publish(UserMessage(session_id="s1", content="a"))
    await bus.publish(UserMessage(session_id="s1", content="b"))

    seen = []
    async for event in bus.subscribe("s1"):
        assert isinstance(event, UserMessage)
        seen.append(event.content)
        if len(seen) == 2:
            break

    assert seen == ["a", "b"]


@pytest.mark.asyncio
async def test_in_memory_bus_fans_out_live_events():
    bus = InMemoryEventBus()
    received: list[str] = []

    async def consume():
        async for event in bus.subscribe("s1"):
            assert isinstance(event, UserMessage)
            received.append(event.content)
            if event.content == "stop":
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber attach
    await bus.publish(UserMessage(session_id="s1", content="live"))
    await bus.publish(UserMessage(session_id="s1", content="stop"))
    await task

    assert received == ["live", "stop"]


@pytest.mark.asyncio
async def test_in_memory_bus_isolates_sessions_and_blocks_until_published():
    """A subscriber sees only its own session, and blocks until one arrives."""
    bus = InMemoryEventBus()
    await bus.publish(UserMessage(session_id="s1", content="only-s1"))

    async def consume():
        async for event in bus.subscribe("s2"):
            assert isinstance(event, UserMessage)
            return event.content

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert not task.done()  # s1's event must not leak into s2

    await bus.publish(UserMessage(session_id="s2", content="finally"))
    assert await task == "finally"
