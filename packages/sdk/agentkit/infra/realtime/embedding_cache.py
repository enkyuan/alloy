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

from agentkit.core.redis import get_redis_client

logger = logging.getLogger(__name__)

_DEFAULT_KEY = "agent:tool_embeddings:v1"
_DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class RedisEmbeddingCache:
    """Durable tool-embedding cache stored as a msgpack blob in Redis.

    NOTE: this needs a Redis client created WITHOUT ``decode_responses=True``
    (msgpack is binary). The shared ``get_redis_client()`` currently decodes
    responses to ``str``, so ``load`` will fail to unpack and fall back to a
    cold recompute. Tracked as a follow-up; wire a bytes-mode client to make the
    cache effective.
    """

    def __init__(
        self, cache_key: str = _DEFAULT_KEY, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        self.cache_key = cache_key
        self.ttl_seconds = ttl_seconds

    async def load(self) -> Dict[str, List[float]]:
        redis = await get_redis_client()
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
        redis = await get_redis_client()
        await redis.setex(
            self.cache_key,
            self.ttl_seconds,
            cast(bytes, msgpack.packb(embeddings)),
        )
