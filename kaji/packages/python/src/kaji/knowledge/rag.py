"""Document RAG: ingest documents, retrieve relevant chunks for a query.

Infra-free by default: without an ``Embedder`` the RAG stores and retrieves
nothing. Inject an ``Embedder`` and optional ``VectorStore`` to enable
retrieval and swap backends.

Pass a ``DocumentRAG`` instance to ``AgentRuntime(rag=...)`` to automatically
retrieve and inject context into the system prompt on every turn.
"""

import logging
from typing import List, Optional

from kaji.core.safe_logging import log_redacted_failure
from kaji.knowledge.chunking import chunk_text
from kaji.knowledge.store import InMemoryVectorStore, VectorStore
from kaji.knowledge.types import Chunk, Document
from kaji.runtime.tools.retriever import Embedder

logger = logging.getLogger(__name__)


class DocumentRAG:
    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> None:
        self._embedder = embedder
        self._store = store if store is not None else InMemoryVectorStore()
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

        if self._embedder is None:
            if pieces:
                logger.warning(
                    "DocumentRAG.add_document stored 0 of %d chunks for %r: no "
                    "embedder was configured. Pass embedder=... to DocumentRAG(...).",
                    len(pieces),
                    document.id,
                )
            return 0

        chunks: List[Chunk] = []
        for i, piece in enumerate(pieces):
            try:
                vec = await self._embedder.embed(piece)
            except Exception as error:  # embedder failure must not crash ingestion
                log_redacted_failure(
                    logger,
                    logging.WARNING,
                    "Document chunk embedding failed",
                    error,
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

        # A silent 0 from non-empty text almost always means no embedder was
        # configured. Surface the cause and fix rather than leaving it ambiguous.
        if not chunks and pieces:
            logger.warning(
                "DocumentRAG.add_document stored 0 of %d chunks for %r: the embedder "
                "returned no vectors. Pass embedder=... to DocumentRAG(...).",
                len(pieces),
                document.id,
            )
        return len(chunks)

    async def retrieve(
        self, query: str, top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        """Return the chunks most relevant to ``query`` (possibly empty)."""
        if self._embedder is None:
            return []
        try:
            query_vec = await self._embedder.embed(query)
        except Exception as error:
            log_redacted_failure(
                logger, logging.WARNING, "Failed to embed RAG query", error
            )
            return []
        if not query_vec:
            return []
        return await self._store.search(query_vec, top_k=top_k, threshold=threshold)
