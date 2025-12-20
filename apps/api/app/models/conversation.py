"""Conversation model for chat history."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    """Conversation model representing a chat session.

    Attributes:
        id: Unique identifier
        user_id: Reference to the user
        title: Optional title of the conversation
        created_at: Creation timestamp
        updated_at: Last update timestamp
        metadata: Additional metadata (JSON)
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String)

    # Store messages in a separate table usually, but for simplicity they might be just related here
    # or stored in vector store chunks.
    # For now let's just keep metadata.
    meta_data: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", backref="conversations")
