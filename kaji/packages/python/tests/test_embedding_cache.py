import msgpack
import pytest
from types import SimpleNamespace

from kaji.infra.realtime import embedding_cache
from kaji.infra.realtime.embedding_cache import RedisEmbeddingCache


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.setex_calls = []
        self.delete_calls = []

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.values[key] = value

    async def delete(self, key):
        self.delete_calls.append(key)
        self.values.pop(key, None)


def test_redis_embedding_cache_defaults_to_new_embedding_generation():
    cache = RedisEmbeddingCache()

    assert cache.cache_identity == "gemini:gemini-embedding-2:v3"
    assert cache.cache_key == ("agent:tool_embeddings:v3:gemini:gemini-embedding-2")


def test_redis_embedding_cache_key_changes_with_configured_model(monkeypatch):
    monkeypatch.setattr(
        embedding_cache,
        "get_settings",
        lambda: SimpleNamespace(GEMINI_EMBEDDING_MODEL="gemini-embedding-custom"),
    )

    cache = RedisEmbeddingCache()

    assert cache.cache_identity == "gemini:gemini-embedding-custom:v3"
    assert cache.cache_key.endswith(":gemini-embedding-custom")


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
    assert msgpack.unpackb(packed, strict_map_key=False) == {
        "identity": "gemini:gemini-embedding-2:v3",
        "dimension": 2,
        "embeddings": {"weather": [1.0, 0.5]},
    }
    assert await cache.load() == {"weather": [1.0, 0.5]}


@pytest.mark.asyncio
async def test_redis_embedding_cache_rejects_model_identity_change(monkeypatch):
    redis = _FakeRedis()

    async def fake_binary_client():
        return redis

    monkeypatch.setattr(
        embedding_cache,
        "get_redis_binary_client",
        fake_binary_client,
    )

    old_cache = RedisEmbeddingCache(cache_key="embeddings", model="old-model")
    await old_cache.save({"weather": [1.0, 0.5]})

    new_cache = RedisEmbeddingCache(cache_key="embeddings", model="new-model")
    assert await new_cache.load() == {}
    assert redis.delete_calls == ["embeddings"]


@pytest.mark.asyncio
async def test_redis_embedding_cache_discards_malformed_msgpack(monkeypatch):
    redis = _FakeRedis()

    async def fake_binary_client():
        return redis

    monkeypatch.setattr(
        embedding_cache,
        "get_redis_binary_client",
        fake_binary_client,
    )

    cache = RedisEmbeddingCache(cache_key="embeddings")
    redis.values["embeddings"] = b"\xc1"

    assert await cache.load() == {}
    assert redis.delete_calls == ["embeddings"]


@pytest.mark.asyncio
async def test_redis_embedding_cache_rejects_mixed_dimensions(monkeypatch):
    redis = _FakeRedis()

    async def fake_binary_client():
        return redis

    monkeypatch.setattr(
        embedding_cache,
        "get_redis_binary_client",
        fake_binary_client,
    )
    cache = RedisEmbeddingCache(cache_key="embeddings")
    redis.values["embeddings"] = msgpack.packb(
        {
            "identity": cache.cache_identity,
            "dimension": 2,
            "embeddings": {
                "weather": [1.0, 0.5],
                "calendar": [1.0, 0.5, 0.25],
            },
        },
        use_bin_type=True,
    )

    assert await cache.load() == {}
    assert redis.delete_calls == ["embeddings"]
