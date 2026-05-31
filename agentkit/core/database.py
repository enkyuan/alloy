"""Database configuration and session management."""

import logging
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from agentkit.core.config import get_settings

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


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    """Return the process-wide async engine, built on first use.

    Deferred (rather than created at import time) so importing this module does
    not require ``DATABASE_URL``; the engine is constructed only when a database
    session is actually needed.
    """
    settings = get_settings()
    return create_async_engine(
        _to_async_database_url(settings.DATABASE_URL),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
        echo=settings.DEBUG,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker:
    """Return the process-wide async sessionmaker, bound to the lazy engine."""
    return async_sessionmaker(
        bind=get_async_engine(),
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


class Base(DeclarativeBase):
    """Base declarative model class."""

    pass


def __getattr__(name: str) -> Any:
    # PEP 562: resolve ``async_engine`` / ``AsyncSessionLocal`` lazily so that
    # importers (``from agentkit.core.database import AsyncSessionLocal``) keep
    # working without building the engine at import time. Note: this does NOT
    # fire for references *within this module* — internal code must call the
    # factories directly.
    if name == "async_engine":
        return get_async_engine()
    if name == "AsyncSessionLocal":
        return get_sessionmaker()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_db():
    """Dependency to get async database session.

    Yields:
        AsyncSession: SQLAlchemy async database session

    Note:
        This is used as a FastAPI dependency to manage database sessions.
        The session is automatically closed after the request is complete.
    """
    async with get_sessionmaker()() as db:
        try:
            yield db
        except Exception as e:
            logger.error("Database session error: %s", e)
            await db.rollback()
            raise


async def close_async_engine() -> None:
    """Dispose async SQLAlchemy engine."""
    try:
        await get_async_engine().dispose()
    except ValueError as error:
        if "greenlet library is required" in str(error).lower():
            logger.warning(
                "Skipping async engine dispose because greenlet is unavailable"
            )
            return
        raise
