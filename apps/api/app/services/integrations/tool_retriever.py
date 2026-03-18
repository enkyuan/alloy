"""Dynamic semantic tool retrieval using vector embeddings."""

import math
import logging
import asyncio
from typing import Dict, List, Optional, Tuple, cast

import msgpack
from app.core.redis import get_redis_client
from app.services.integrations import list_tool_specs
from app.services.pipeline.services.gemini_service import get_gemini_service

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
        # Returns List[float] natively via gemini_service
        embedding = await gemini.embed_text(text)
        if not embedding:
             return []
        
        # Google-GenAI typing may return various formats, ensuring fallback casting
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
            
            # 1. Attempt to load globally cached vectors across network cluster
            try:
                cached_bytes = await redis.get(cache_key)
                if cached_bytes:
                    raw_cache = msgpack.unpackb(cached_bytes, strict_map_key=False)
                    if isinstance(raw_cache, dict):
                        # Ensure keys decode cleanly from bytes if transported
                        self._embeddings = {
                            k.decode("utf-8") if isinstance(k, bytes) else k: v 
                            for k, v in raw_cache.items()
                        }
                        logger.info(f"0ms Boot: Successfully loaded {len(self._embeddings)} tool vectors instantly from Redis.")
            except Exception as e:
                logger.warning(f"Failed to load cached tool embeddings from Redis: {e}")
                
            # 2. Reconcile any missing/new tools dynamically over the network
            specs = list_tool_specs()
            needs_update = False
            
            for spec in specs:
                if spec.name not in self._embeddings:
                    repr_text = f"Tool: {spec.name}. Description: {spec.description}. Parameters: {spec.parameters}"
                    logger.debug(f"Computing new embedding for unseen tool: {spec.name}")
                    try:
                        vec = await self._embed_text(repr_text)
                        if vec:
                            self._embeddings[spec.name] = vec
                            needs_update = True
                    except Exception as e:
                        logger.error(f"Failed to embed tool {spec.name}: {e}")

            # 3. Cache the newly computed hybrid-dictionary seamlessly across the entire server farm
            if needs_update and self._embeddings:
                try:
                    await redis.setex(
                        cache_key,
                        30 * 24 * 3600, # Persist for 30 days
                        cast(bytes, msgpack.packb(self._embeddings))
                    )
                    logger.info(f"Globally cached updated network matrix for {len(self._embeddings)} tools into Redis.")
                except Exception as e:
                    logger.error(f"Failed to persist tool embeddings to Redis: {e}")

            self._initialized = True

    async def get_top_tools(self, query: str, top_k: int = 5, threshold: float = 0.6) -> List[str]:
        """Returns the top `k` most logically relevant tools based on cosine similarity."""
        await self.initialize()

        if not self._embeddings:
            logger.warning("Tool RAG index is empty. Returning all tools natively as fallback.")
            return [spec.name for spec in list_tool_specs()]

        try:
            query_vec = await self._embed_text(query)
        except Exception as e:
            logger.error(f"Failed to embed query for tool RAG: {e}. Falling back to all tools.")
            return [spec.name for spec in list_tool_specs()]

        scores: List[Tuple[str, float]] = []
        for tool_name, tool_vec in self._embeddings.items():
            sim = cosine_similarity(query_vec, tool_vec)
            scores.append((tool_name, sim))

        # Sort highest similarity first
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Extract the highest scoring tools
        top_tools = [name for name, score in scores[:top_k] if score >= threshold]
        
        if top_tools:
            logger.info(f"Vector RAG matched {len(top_tools)} tools for query: {top_tools}")
            return top_tools
            
        logger.debug(f"No tools exceeded similarity threshold {threshold}. Query: '{query[:50]}'")
        return []


_retriever: Optional[ToolRetriever] = None

def get_tool_retriever() -> ToolRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ToolRetriever()
    return _retriever
