import msgpack
import pytest

from kaji.infra.realtime import embedding_cache
from kaji.infra.realtime.embedding_cache import RedisEmbeddingCache


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.setex_calls = []

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.values[key] = value


@pytest.mark.asyncio
async def test_redis_embedding_cache_uses_binary_msgpack_client(monkeypatch):
    redis = _FakeRedis()

    async def fake_binary_client():
        return redis

    monkeypatch.setattr(
        embedding_cache,
        "get_redis_binary_client",
        fake_binary_client,
    )

    cache = RedisEmbeddingCache(cache_key="embeddings", ttl_seconds=60)
    await cache.save({"weather": [1.0, 0.5]})

    key, ttl, packed = redis.setex_calls[0]
    assert key == "embeddings"
    assert ttl == 60
    assert isinstance(packed, bytes)
    assert msgpack.unpackb(packed, strict_map_key=False) == {"weather": [1.0, 0.5]}
    assert await cache.load() == {"weather": [1.0, 0.5]}
