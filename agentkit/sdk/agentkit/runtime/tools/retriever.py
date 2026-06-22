"""Dynamic semantic tool retrieval using vector embeddings.

Both the embedding backend and the embedding cache are pluggable. By default
the retriever is infra-free: it uses a lazily-constructed Gemini embedder (only
if ``GEMINI_API_KEY`` is set; otherwise it embeds nothing and falls back to
returning all tools) and an in-memory cache. Inject a different ``Embedder`` or
``EmbeddingCache`` to use another provider or a durable cache (e.g. the Redis
cache the reference service wires up).
"""

import asyncio
import logging
from typing import Dict, List, Optional, Protocol, Tuple

from agentkit.runtime.tools._vector_math import cosine_similarity
from agentkit.runtime.tools.registry import list_tool_specs

logger = logging.getLogger(__name__)

CosineSimilarity = cosine_similarity

__all__ = [
    "CosineSimilarity",
    "Embedder",
    "EmbeddingCache",
    "GetToolRetriever",
    "ToolRetriever",
]


class Embedder(Protocol):
    """Turns text into a vector. Return an empty list to signal "no embedding"."""

    async def embed(self, text: str) -> List[float]: ...


class EmbeddingCache(Protocol):
    """Persists the tool-name -> vector map between runs."""

    async def load(self) -> Dict[str, List[float]]: ...

    async def save(self, embeddings: Dict[str, List[float]]) -> None: ...


class GeminiEmbedder:
    """Default embedder. Constructs the Gemini service lazily on first use.

    Importing this module therefore costs nothing; the Gemini client (and its
    ``GEMINI_API_KEY`` requirement) is only touched when ``embed`` is actually
    called. If the key is missing it returns an empty vector rather than raising,
    so the retriever degrades to returning all tools.
    """

    def __init__(self) -> None:
        self._service = None

    async def embed(self, text: str) -> List[float]:
        if self._service is None:
            from agentkit.runtime.providers.gemini import get_gemini_service

            try:
                self._service = get_gemini_service()
            except Exception as e:  # missing key, missing package, etc.
                logger.warning("Gemini embedder unavailable: %s", e)
                return []

        embedding = await self._service.embed_text(text)
        if not embedding:
            return []
        if hasattr(embedding, "values"):
            return list(embedding.values)
        return list(embedding)


class InMemoryEmbeddingCache:
    """Process-local cache — no infra. Lost on restart (recomputed lazily)."""

    def __init__(self) -> None:
        self._store: Dict[str, List[float]] = {}

    async def load(self) -> Dict[str, List[float]]:
        return dict(self._store)

    async def save(self, embeddings: Dict[str, List[float]]) -> None:
        self._store = dict(embeddings)


class ToolRetriever:
    """In-memory vector retrieval for RAG-based tool calling."""

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        cache: Optional[EmbeddingCache] = None,
    ) -> None:
        self._embedder: Embedder = embedder or GeminiEmbedder()
        self._cache: EmbeddingCache = cache or InMemoryEmbeddingCache()
        self._embeddings: Dict[str, List[float]] = {}
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _embed_text(self, text: str) -> List[float]:
        return await self._embedder.embed(text)

    async def initialize(self) -> None:
        """Pre-compute embeddings for all registered tools (cache-backed)."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            logger.info("Initializing vector RAG index for tool representations...")

            try:
                self._embeddings = await self._cache.load()
                if self._embeddings:
                    logger.info(
                        "Loaded %s tool vectors from cache.", len(self._embeddings)
                    )
            except Exception as e:
                logger.warning("Failed to load cached tool embeddings: %s", e)
                self._embeddings = {}

            needs_update = False
            for spec in list_tool_specs():
                if spec.name in self._embeddings:
                    continue
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
                    await self._cache.save(self._embeddings)
                    logger.info(
                        "Cached embeddings for %s tools.", len(self._embeddings)
                    )
                except Exception as e:
                    logger.error("Failed to persist tool embeddings: %s", e)

            self._initialized = True

    async def get_top_tools(
        self, query: str, top_k: int = 5, threshold: float = 0.6
    ) -> List[str]:
        """Return the top ``k`` most relevant tools by cosine similarity.

        Falls back to all registered tool names when no embeddings are available
        (e.g. no embedder configured), so retrieval never blocks tool use.
        """
        await self.initialize()

        if not self._embeddings:
            return [spec.name for spec in list_tool_specs()]

        try:
            query_vec = await self._embed_text(query)
        except Exception as e:
            logger.error("Failed to embed query for tool RAG: %s", e)
            return [spec.name for spec in list_tool_specs()]

        if not query_vec:
            return [spec.name for spec in list_tool_specs()]

        scores: List[Tuple[str, float]] = []
        for tool_name, tool_vec in self._embeddings.items():
            sim = cosine_similarity(query_vec, tool_vec)
            scores.append((tool_name, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        top_tools = [name for name, score in scores[:top_k] if score >= threshold]

        if top_tools:
            logger.info(
                "Vector RAG matched %s tools for query: %s", len(top_tools), top_tools
            )
            return top_tools

        return []


_retriever: Optional[ToolRetriever] = None


def get_tool_retriever() -> ToolRetriever:
    global _retriever
    if _retriever is None:
        _retriever = ToolRetriever()
    return _retriever


GetToolRetriever = get_tool_retriever
