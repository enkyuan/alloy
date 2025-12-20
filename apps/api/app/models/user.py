"""User model for the application."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    """User model representing authenticated users.

    This model stores user information synced from Supabase Auth.
    Users are created via OAuth providers (Google, Apple) or email.

    Attributes:
        id: Unique user identifier (from Supabase)
        email: User's email address
        username: Optional username
        full_name: User's full name
        avatar_url: URL to user's profile picture
        provider: OAuth provider (google, apple, email)
        provider_id: Provider-specific user ID
        is_active: Whether user account is active
        is_verified: Whether user's email is verified
        created_at: Account creation timestamp
        updated_at: Last update timestamp
        last_login: Last login timestamp
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String)
    avatar_url: Mapped[Optional[str]] = mapped_column(String)

    # OAuth provider info
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default="email"
    )  # google, apple, email
    provider_id: Mapped[Optional[str]] = mapped_column(String, index=True)

    # Account status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    integrations = relationship(
        "Integration", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, username={self.username})>"
