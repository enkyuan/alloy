import base64
import json
from typing import cast

import pytest

from kaji.infra.realtime.redis import RedisKeys
from kaji.infra.realtime.dedup import (
    claim_tool_call_execution,
    is_tool_call_execution_complete,
    mark_tool_call_execution_complete,
)
from kaji.infra.realtime.dlq import (
    build_generic_dlq_entry,
    parse_generic_dlq_entry,
)
from kaji.infra.realtime.publish import drain_user_update_outbox

try:
    import fakeredis.aioredis as _fakeredis_async  # type: ignore[import]

    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False


def test_generic_dlq_entry_round_trips_msgpack_payload() -> None:
    raw = build_generic_dlq_entry(
        {"tool": "lookup", "args": {"q": "weather"}},
        reason="stream_failed",
        attempts=2,
        message_id="1-0",
    )

    payload, attempts, reason, extras = parse_generic_dlq_entry(raw)

    assert payload == {"tool": "lookup", "args": {"q": "weather"}}
    assert attempts == 2
    assert reason == "stream_failed"
    assert extras == {"message_id": "1-0"}


def test_generic_dlq_entry_can_coerce_redis_stream_fields() -> None:
    raw = build_generic_dlq_entry(
        {b"_msgpack": b"payload"},
        attempts=cast(int, "bad"),
        coerce_fields=True,
    )

    payload, attempts, reason, extras = parse_generic_dlq_entry(raw)

    assert payload == {"_msgpack": "payload"}
    assert attempts == 0
    assert reason is None
    assert extras == {}


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_FAKEREDIS, reason="fakeredis not installed")
async def test_tool_call_execution_dedup_marks_complete() -> None:
    redis = _fakeredis_async.FakeRedis()

    assert await claim_tool_call_execution(redis, tool_call_id="call-1") is True
    assert await claim_tool_call_execution(redis, tool_call_id="call-1") is False
    assert await is_tool_call_execution_complete(redis, tool_call_id="call-1") is False

    await mark_tool_call_execution_complete(redis, tool_call_id="call-1")

    assert await is_tool_call_execution_complete(redis, tool_call_id="call-1") is True
    await redis.aclose()


@pytest.mark.asyncio
async def test_drain_user_update_outbox_publishes_encoded_payload() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.queue: list[str] = []
            self.published: list[tuple[str, bytes]] = []

        async def lpush(self, key, value):
            self.queue.insert(0, value)

        async def rpop(self, key):
            if not self.queue:
                return None
            return self.queue.pop()

        async def rpush(self, key, value):
            self.queue.append(value)

        async def llen(self, key):
            return len(self.queue)

        async def publish(self, channel, payload):
            self.published.append((channel, payload))

    redis = FakeRedis()
    payload = b"packed-event"
    await redis.lpush(
        RedisKeys.USER_UPDATE_OUTBOX_KEY,
        json.dumps({"payload_b64": base64.b64encode(payload).decode("ascii")}),
    )

    drained = await drain_user_update_outbox(redis, channel="test-channel")

    assert drained == 1
    assert await redis.llen(RedisKeys.USER_UPDATE_OUTBOX_KEY) == 0
    assert redis.published == [("test-channel", payload)]
