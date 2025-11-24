"""Integration model for third-party service OAuth tokens."""

from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


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

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    service = Column(String, nullable=False, index=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    token_type = Column(String, default="Bearer")
    expires_at = Column(DateTime, nullable=True)
    scope = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="integrations")
