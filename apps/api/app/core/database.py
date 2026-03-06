"""Database configuration and session management."""

import logging

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


def _to_async_database_url(database_url: str) -> str:
    """Return an async SQLAlchemy URL derived from DATABASE_URL."""
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("sqlite+aiosqlite://"):
        return database_url
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return database_url


async_engine = create_async_engine(
    _to_async_database_url(settings.DATABASE_URL),
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    echo=settings.DEBUG,
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base declarative model class."""

    pass


async def get_db():
    """Dependency to get async database session.

    Yields:
        AsyncSession: SQLAlchemy async database session

    Note:
        This is used as a FastAPI dependency to manage database sessions.
        The session is automatically closed after the request is complete.
    """
    async with AsyncSessionLocal() as db:
        try:
            yield db
        except Exception as e:
            logger.error("Database session error: %s", e)
            await db.rollback()
            raise


async def close_async_engine() -> None:
    """Dispose async SQLAlchemy engine."""
    try:
        await async_engine.dispose()
    except ValueError as error:
        if "greenlet library is required" in str(error).lower():
            logger.warning(
                "Skipping async engine dispose because greenlet is unavailable"
            )
            return
        raise
