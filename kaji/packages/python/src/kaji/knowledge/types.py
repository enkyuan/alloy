"""Document and chunk types for the knowledge/RAG subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Document:
    """A source document to be ingested into the vector store."""

    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A chunk of a document, the unit of retrieval."""

    document_id: str
    text: str
    index: int  # position within the source document
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: List[float] = field(default_factory=list)
