"""Integration model for third-party service OAuth tokens."""

from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Integration(Base):
    """Integration model representing OAuth connections to third-party services.

    Attributes:
        id: Unique identifier for the integration
        user_id: Reference to the user who owns this integration
        service: Service name (spotify, uber, gmail, etc.)
        access_token: OAuth access token
        refresh_token: OAuth refresh token (if provided)
        token_type: Token type (usually "Bearer")
        expires_at: Timestamp when the access token expires
        scope: Granted OAuth scopes
        is_active: Whether the integration is currently active
        created_at: Timestamp when the integration was created
        updated_at: Timestamp when the integration was last updated
    """

    __tablename__ = "integrations"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String, nullable=False, index=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String, default="Bearer")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    user = relationship("User", back_populates="integrations")
