"""Redis-backed embedding cache for the tool retriever (opt-in).

Satisfies the retriever's ``EmbeddingCache`` protocol. Lives here, in the
realtime/Redis layer, so importing ``runtime.tools.retriever`` pulls in no Redis
dependency — the SDK's default cache is in-memory. Wire this in explicitly when
you want tool embeddings to survive restarts::

    from kaji.infra.realtime.embedding_cache import RedisEmbeddingCache
    from kaji.runtime.tools.retriever import ToolRetriever

    retriever = ToolRetriever(cache=RedisEmbeddingCache())
"""

import logging
import math
from typing import Dict, List, cast
from urllib.parse import quote

import msgpack

from kaji.core.config import get_settings
from kaji.infra.realtime.redis import get_redis_binary_client

logger = logging.getLogger(__name__)

_CACHE_GENERATION = "v3"
_DEFAULT_PROVIDER = "gemini"
_DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days


class RedisEmbeddingCache:
    """Durable, model-scoped tool-embedding cache stored in Redis.

    The key and payload both carry the provider/model/generation identity. The
    payload also records its vector dimension so corrupt or stale mixed-model
    data is discarded instead of being used for similarity scoring.
    """

    def __init__(
        self,
        cache_key: str | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        *,
        provider: str = _DEFAULT_PROVIDER,
        model: str | None = None,
        generation: str = _CACHE_GENERATION,
    ) -> None:
        resolved_model = model or get_settings().GEMINI_EMBEDDING_MODEL
        self.cache_identity = f"{provider}:{resolved_model}:{generation}"
        escaped_model = quote(resolved_model, safe="-._")
        self.cache_key = cache_key or (
            f"agent:tool_embeddings:{generation}:{provider}:{escaped_model}"
        )
        self.ttl_seconds = ttl_seconds

    async def load(self) -> Dict[str, List[float]]:
        redis = await get_redis_binary_client()
        cached_bytes = await redis.get(self.cache_key)
        if not cached_bytes:
            return {}
        try:
            raw = msgpack.unpackb(cached_bytes, strict_map_key=False)
        except (TypeError, ValueError, msgpack.exceptions.UnpackException):
            await redis.delete(self.cache_key)
            return {}
        if not isinstance(raw, dict):
            await redis.delete(self.cache_key)
            return {}

        identity = raw.get("identity")
        dimension = raw.get("dimension")
        embeddings = raw.get("embeddings")
        if (
            identity != self.cache_identity
            or not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
            or not isinstance(embeddings, dict)
        ):
            await redis.delete(self.cache_key)
            return {}

        validated: Dict[str, List[float]] = {}
        for name, vector in embeddings.items():
            if not isinstance(name, str) or not isinstance(vector, list):
                await redis.delete(self.cache_key)
                return {}
            if len(vector) != dimension or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in vector
            ):
                await redis.delete(self.cache_key)
                return {}
            validated[name] = [float(value) for value in vector]
        return validated

    async def save(self, embeddings: Dict[str, List[float]]) -> None:
        redis = await get_redis_binary_client()
        if not embeddings:
            await redis.delete(self.cache_key)
            return

        dimensions = {len(vector) for vector in embeddings.values() if vector}
        if len(dimensions) != 1 or any(not vector for vector in embeddings.values()):
            raise ValueError("all cached embeddings must have one non-zero dimension")

        payload = {
            "identity": self.cache_identity,
            "dimension": dimensions.pop(),
            "embeddings": embeddings,
        }
        await redis.setex(
            self.cache_key,
            self.ttl_seconds,
            cast(bytes, msgpack.packb(payload, use_bin_type=True)),
        )
