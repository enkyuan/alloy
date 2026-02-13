"""Conversation model for chat history."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
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

    # SQLAlchemy reserves `metadata` on mapped classes, so the DB column remains
    # `meta_data` and we provide a clearer Python alias via `metadata_json`.
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

    @property
    def metadata_json(self) -> Optional[dict]:
        return self.meta_data

    @metadata_json.setter
    def metadata_json(self, value: Optional[dict]) -> None:
        self.meta_data = value
