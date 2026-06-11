"""Document RAG: ingest documents, retrieve relevant chunks for a query.

Infra-free by default: the embedder defaults to the same lazily-constructed
``GeminiEmbedder`` the tool retriever uses (returns ``[]`` with no key, so the
whole thing degrades to "stores nothing / retrieves nothing" rather than
raising). Inject any ``Embedder`` and ``VectorStore`` to swap backends.

This builds the retrieval *capability*. Auto-injecting retrieved context into
``AgentRuntime`` (when to retrieve, how to ground the prompt) is intentionally
left to a future memory-injection design - see ROADMAP item 14.
"""

import logging
from typing import List, Optional

from agentkit.knowledge.chunking import chunk_text
from agentkit.knowledge.store import InMemoryVectorStore, VectorStore
from agentkit.knowledge.types import Chunk, Document
from agentkit.runtime.tools.retriever import Embedder, GeminiEmbedder

logger = logging.getLogger(__name__)


class DocumentRAG:
    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> None:
        self._embedder: Embedder = embedder or GeminiEmbedder()
        self._store: VectorStore = store or InMemoryVectorStore()
        self._chunk_size = chunk_size
        self._overlap = overlap

    async def add_document(
        self,
        document: Document,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
    ) -> int:
        """Chunk, embed, and store a document. Returns the number of chunks stored."""
        size = chunk_size if chunk_size is not None else self._chunk_size
        ov = overlap if overlap is not None else self._overlap
        pieces = chunk_text(document.text, size=size, overlap=ov)

        chunks: List[Chunk] = []
        for i, piece in enumerate(pieces):
            try:
                vec = await self._embedder.embed(piece)
            except Exception as e:  # embedder failure must not crash ingestion
                logger.warning(
                    "Embedding failed for %s chunk %d: %s", document.id, i, e
                )
                vec = []
            if not vec:
                continue
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=piece,
                    index=i,
                    metadata=dict(document.metadata),
                    embedding=vec,
                )
            )

        await self._store.add(chunks)

        # F3: a silent 0 from non-empty text almost always means "no embedder
        # configured" (e.g. GEMINI_API_KEY unset -> GeminiEmbedder returns []).
        # Surface it as problem + cause + fix rather than letting the dev wonder.
        if not chunks and pieces:
            logger.warning(
                "DocumentRAG.add_document stored 0 of %d chunks for %r: the embedder "
                "returned no vectors. Set GEMINI_API_KEY or pass embedder=... to "
                "DocumentRAG(...).",
                len(pieces),
                document.id,
            )
        return len(chunks)

    async def retrieve(
        self, query: str, top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        """Return the chunks most relevant to ``query`` (possibly empty)."""
        try:
            query_vec = await self._embedder.embed(query)
        except Exception as e:
            logger.error("Failed to embed RAG query: %s", e)
            return []
        if not query_vec:
            return []
        return await self._store.search(query_vec, top_k=top_k, threshold=threshold)
