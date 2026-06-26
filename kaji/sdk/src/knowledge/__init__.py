"""Kaji knowledge subsystem: document ingestion and retrieval (RAG)."""

from kaji.knowledge.chunking import chunk_text
from kaji.knowledge.rag import DocumentRAG
from kaji.knowledge.store import InMemoryVectorStore, VectorStore
from kaji.knowledge.types import Chunk, Document

ChunkText = chunk_text

__all__ = [
    "Chunk",
    "ChunkText",
    "Document",
    "DocumentRAG",
    "InMemoryVectorStore",
    "VectorStore",
]
