"""Compatibility helpers for sync and async SQLAlchemy sessions."""

from __future__ import annotations

import inspect
from typing import Any


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def db_execute(session: Any, statement: Any, params: dict[str, Any] | None = None) -> Any:
    """Execute a SQL statement against either sync or async SQLAlchemy session."""
    if params is None:
        return await _maybe_await(session.execute(statement))
    return await _maybe_await(session.execute(statement, params))


async def db_commit(session: Any) -> None:
    """Commit either sync or async SQLAlchemy session."""
    await _maybe_await(session.commit())


async def db_refresh(session: Any, instance: Any) -> None:
    """Refresh ORM instance using either sync or async SQLAlchemy session."""
    await _maybe_await(session.refresh(instance))


async def db_rollback(session: Any) -> None:
    """Rollback either sync or async SQLAlchemy session."""
    await _maybe_await(session.rollback())


async def db_close(session: Any) -> None:
    """Close either sync or async SQLAlchemy session."""
    await _maybe_await(session.close())
