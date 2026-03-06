"""Vector Embedding model for RAG."""

from datetime import datetime, timezone
from typing import List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import MetadataJsonMixin

class VectorEmbedding(MetadataJsonMixin, Base):
    """Vector Embedding model for semantic search.

    Attributes:
        id: Unique identifier
        content: The text content chunk
        embedding: The vector embedding (1536 dimensions for text-embedding-3-small)
        metadata: Additional metadata (source, page, etc.)
        user_id: Reference to the user (for RLS)
        created_at: Creation timestamp
    """

    __tablename__ = "vector_embeddings"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Using 1536 dimensions as standard for OpenAI/Gemini embeddings usually
    # Gemini text-embedding-004 is 768 dimensions.
    # Let's assume 768 for Gemini or 1536.
    # I'll use Vector(768) as a default for Gemini.
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(768))

    # SQLAlchemy reserves `metadata` on mapped classes, so the DB column remains
    # `meta_data` and we provide a clearer Python alias via `metadata_json`.
    meta_data: Mapped[Optional[dict]] = mapped_column(JSONB)

    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    user = relationship("User", backref="embeddings")
