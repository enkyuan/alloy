"""Vector store for document chunks. Infra-free in-memory default.

The protocol mirrors the spirit of ``EventStore``: a narrow interface a durable
backend (pgvector, etc., in agentkit-serve) can implement later. The bundled
``InMemoryVectorStore`` does an exact cosine scan, fine for embedded use and
tests, not for millions of chunks.
"""

import logging
from typing import List, Protocol

from agentkit.knowledge.types import Chunk
from agentkit.runtime.tools._vector_math import cosine_similarity

logger = logging.getLogger(__name__)


class VectorStore(Protocol):
    """Stores embedded chunks and returns the nearest by cosine similarity."""

    async def add(self, chunks: List[Chunk]) -> None: ...

    async def search(
        self, query_embedding: List[float], top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]: ...


class InMemoryVectorStore:
    """Process-local exact-cosine vector store. Lost on restart.

    Assumes one embedder per store: every chunk should share the query's
    embedding dimension. Chunks whose dimension differs are skipped at search
    time (see ``search``), never silently truncated.
    """

    def __init__(self) -> None:
        self._chunks: List[Chunk] = []

    async def add(self, chunks: List[Chunk]) -> None:
        # Only keep chunks that carry an embedding; an empty vector can never match.
        self._chunks.extend(c for c in chunks if c.embedding)

    async def search(
        self, query_embedding: List[float], top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        if not query_embedding or not self._chunks:
            return []
        dim = len(query_embedding)
        scored = []
        for c in self._chunks:
            # H4: cosine_similarity uses zip(), which silently truncates on a
            # dimension mismatch. Skip chunks whose embedding dim differs from
            # the query's (e.g. the embedder was swapped under a populated store)
            # rather than returning a garbage score.
            if len(c.embedding) != dim:
                logger.warning(
                    "Skipping chunk %s/%d: embedding dim %d != query dim %d",
                    c.document_id,
                    c.index,
                    len(c.embedding),
                    dim,
                )
                continue
            scored.append((cosine_similarity(query_embedding, c.embedding), c))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [c for score, c in scored[:top_k] if score >= threshold]
