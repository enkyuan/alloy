import logging

from kaji.infra.realtime.history_ops import append_history, get_history, history_key


class FakeRedisList:
    def __init__(self) -> None:
        self.items: dict[str, list[str]] = {}

    async def lindex(self, key: str, index: int) -> str | None:
        bucket = self.items.get(key, [])
        if not bucket:
            return None
        try:
            return bucket[index]
        except IndexError:
            return None

    async def rpush(self, key: str, value: str) -> None:
        self.items.setdefault(key, []).append(value)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        bucket = self.items.get(key, [])
        length = len(bucket)
        start_idx = start if start >= 0 else max(length + start, 0)
        end_idx = end if end >= 0 else length + end
        self.items[key] = bucket[start_idx : end_idx + 1]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        bucket = self.items.get(key, [])
        length = len(bucket)
        start_idx = start if start >= 0 else max(length + start, 0)
        end_idx = end if end >= 0 else length + end
        return bucket[start_idx : end_idx + 1]


async def test_append_history_stores_role_and_content() -> None:
    redis = FakeRedisList()

    await append_history(redis, "u1", "user", "hello", history_limit=10)

    assert await get_history(redis, "u1") == [{"role": "user", "content": "hello"}]


async def test_append_history_suppresses_adjacent_duplicates() -> None:
    redis = FakeRedisList()

    await append_history(redis, "u1", "user", "hello", history_limit=10)
    await append_history(redis, "u1", "user", "hello", history_limit=10)

    assert await get_history(redis, "u1") == [{"role": "user", "content": "hello"}]


async def test_append_history_trims_to_history_limit() -> None:
    redis = FakeRedisList()

    await append_history(redis, "u1", "user", "one", history_limit=2)
    await append_history(redis, "u1", "assistant", "two", history_limit=2)
    await append_history(redis, "u1", "user", "three", history_limit=2)

    assert await get_history(redis, "u1") == [
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]


async def test_get_history_skips_invalid_json_entries(caplog) -> None:
    redis = FakeRedisList()
    key = history_key("u1")
    redis.items[key] = ["not-json", '{"role":"user","content":"ok"}']

    with caplog.at_level(logging.WARNING):
        messages = await get_history(redis, "u1")

    assert messages == [{"role": "user", "content": "ok"}]
    assert "Skipping invalid history entry" in caplog.text
