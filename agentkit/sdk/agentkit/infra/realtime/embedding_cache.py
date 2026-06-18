"""Redis-backed embedding cache for the tool retriever (opt-in).

Satisfies the retriever's ``EmbeddingCache`` protocol. Lives here, in the
realtime/Redis layer, so importing ``runtime.tools.retriever`` pulls in no Redis
dependency — the SDK's default cache is in-memory. Wire this in explicitly when
you want tool embeddings to survive restarts::

    from agentkit.infra.realtime.embedding_cache import RedisEmbeddingCache
    from agentkit.runtime.tools.retriever import ToolRetriever

    retriever = ToolRetriever(cache=RedisEmbeddingCache())
"""

import logging
from typing import Dict, List, cast

import msgpack

from agentkit.infra.realtime.redis import get_redis_binary_client

logger = logging.getLogger(__name__)

_DEFAULT_KEY = "agent:tool_embeddings:v1"
_DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class RedisEmbeddingCache:
    """Durable tool-embedding cache stored as a msgpack blob in Redis."""

    def __init__(
        self, cache_key: str = _DEFAULT_KEY, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        self.cache_key = cache_key
        self.ttl_seconds = ttl_seconds

    async def load(self) -> Dict[str, List[float]]:
        redis = await get_redis_binary_client()
        cached_bytes = await redis.get(self.cache_key)
        if not cached_bytes:
            return {}
        raw = msgpack.unpackb(cached_bytes, strict_map_key=False)
        if not isinstance(raw, dict):
            return {}
        return {
            (k.decode("utf-8") if isinstance(k, bytes) else k): v
            for k, v in raw.items()
        }

    async def save(self, embeddings: Dict[str, List[float]]) -> None:
        redis = await get_redis_binary_client()
        await redis.setex(
            self.cache_key,
            self.ttl_seconds,
            cast(bytes, msgpack.packb(embeddings)),
        )
