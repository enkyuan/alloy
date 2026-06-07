"""AgentKit knowledge subsystem: document ingestion and retrieval (RAG)."""

from agentkit.knowledge.chunking import chunk_text
from agentkit.knowledge.types import Chunk, Document

__all__ = ["chunk_text", "Chunk", "Document"]
