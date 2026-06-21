"""AgentKit knowledge subsystem: document ingestion and retrieval (RAG)."""

from agentkit.knowledge.chunking import chunk_text
from agentkit.knowledge.rag import DocumentRAG
from agentkit.knowledge.store import InMemoryVectorStore, VectorStore
from agentkit.knowledge.types import Chunk, Document

ChunkText = chunk_text

__all__ = [
    "Chunk",
    "ChunkText",
    "Document",
    "DocumentRAG",
    "InMemoryVectorStore",
    "VectorStore",
]
