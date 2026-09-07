"""Postgres-backed session index for the reference service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kaji.runtime.sessions.store import SessionRecord
from kaji_serve.server.models.conversation import Conversation


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class PostgresSessionStore:
    """SessionStore adapter backed by the existing conversations table."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_session(self, record: SessionRecord) -> None:
        existing = await self._db.get(Conversation, record.session_id)
        if existing is not None:
            return

        created_at = datetime.fromtimestamp(record.created_at, timezone.utc)
        self._db.add(
            Conversation(
                id=record.session_id,
                user_id=record.user_id,
                title=record.title or None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await self._db.flush()

    async def list_sessions(self, user_id: str) -> list[SessionRecord]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
        )
        conversations = result.scalars().all()
        return [
            SessionRecord(
                session_id=conversation.id,
                user_id=conversation.user_id,
                title=conversation.title or "",
                created_at=_timestamp(conversation.created_at),
            )
            for conversation in conversations
        ]
