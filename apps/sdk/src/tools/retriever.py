"""Dynamic semantic tool retrieval using vector embeddings."""

import asyncio
import logging
import math
from typing import Dict, List, Optional, Tuple, cast

import msgpack

from src.core.redis import get_redis_client
from src.providers.gemini import get_gemini_service
from src.tools.registry import list_tool_specs

logger = logging.getLogger(__name__)


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(a * a for a in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


class ToolRetriever:
    """In-memory Vector Retrieval system for RAG-based tool calling."""

    def __init__(self):
        self._embeddings: Dict[str, List[float]] = {}
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _embed_text(self, text: str) -> List[float]:
        gemini = get_gemini_service()
        embedding = await gemini.embed_text(text)
        if not embedding:
            return []

        if hasattr(embedding, "values"):
            return list(embedding.values)
        return list(embedding)

    async def initialize(self) -> None:
        """Pre-computes embeddings for all registered tools or loads from Redis cache."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            logger.info("Initializing Vector RAG index for tool representations...")
            redis = await get_redis_client()
            cache_key = "agent:tool_embeddings:v1"

            try:
                cached_bytes = await redis.get(cache_key)
                if cached_bytes:
                    raw_cache = msgpack.unpackb(cached_bytes, strict_map_key=False)
                    if isinstance(raw_cache, dict):
                        self._embeddings = {
                            k.decode("utf-8") if isinstance(k, bytes) else k: v
                            for k, v in raw_cache.items()
                        }
                        logger.info(
                            "Loaded %s tool vectors from Redis cache.",
                            len(self._embeddings),
                        )
            except Exception as e:
                logger.warning("Failed to load cached tool embeddings from Redis: %s", e)

            specs = list_tool_specs()
            needs_update = False

            for spec in specs:
                if spec.name not in self._embeddings:
                    repr_text = (
                        f"Tool: {spec.name}. Description: {spec.description}. "
                        f"Parameters: {spec.parameters}"
                    )
                    logger.debug("Computing new embedding for tool: %s", spec.name)
                    try:
                        vec = await self._embed_text(repr_text)
                        if vec:
                            self._embeddings[spec.name] = vec
                            needs_update = True
                    except Exception as e:
                        logger.error("Failed to embed tool %s: %s", spec.name, e)

            if needs_update and self._embeddings:
                try:
                    await redis.setex(
                        cache_key,
                        30 * 24 * 3600,
                        cast(bytes, msgpack.packb(self._embeddings)),
                    )
                    logger.info(
                        "Cached embeddings for %s tools in Redis.",
                        len(self._embeddings),
                    )
                except Exception as e:
                    logger.error("Failed to persist tool embeddings to Redis: %s", e)

            self._initialized = True

    async def get_top_tools(
        self, query: str, top_k: int = 5, threshold: float = 0.6
    ) -> List[str]:
        """Returns the top `k` most logically relevant tools based on cosine similarity."""
        await self.initialize()

        if not self._embeddings:
            return [spec.name for spec in list_tool_specs()]

        try:
            query_vec = await self._embed_text(query)
        except Exception as e:
            logger.error("Failed to embed query for tool RAG: %s", e)
            return [spec.name for spec in list_tool_specs()]

        scores: List[Tuple[str, float]] = []
        for tool_name, tool_vec in self._embeddings.items():
            sim = cosine_similarity(query_vec, tool_vec)
            scores.append((tool_name, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_tools = [name for name, score in scores[:top_k] if score >= threshold]

        if top_tools:
            logger.info("Vector RAG matched %s tools for query: %s", len(top_tools), top_tools)
            return top_tools

        return []


_retriever: Optional[ToolRetriever] = None


def get_tool_retriever() -> ToolRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ToolRetriever()
    return _retriever
