"""Postgres implementation of the durable event-store protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from typing import Any

from kaji.events.errors import EventIdConflictError
from kaji.events.schemas import (
    NewKajiEvent,
    StoredKajiEvent,
    revalidate_new_event,
    revalidate_stored_event,
)
from kaji.events.store.base import AppendResult, prepare_stored_event


def _get_psycopg() -> Any:
    """Import the optional Postgres driver only when this adapter is used."""

    try:
        import psycopg  # noqa: PLC0415

        return psycopg
    except ImportError as exc:
        raise ImportError(
            "Postgres support requires `pip install 'kaji[postgres]'`."
        ) from exc


def _draft_payload(event: NewKajiEvent | StoredKajiEvent) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude={"sequence"})


def _decode_event(value: Any) -> StoredKajiEvent:
    if isinstance(value, str):
        value = json.loads(value)
    return revalidate_stored_event(value)


class PostgresEventStore:
    """Durable append-only events using a transactional per-session counter."""

    def __init__(self, dsn: str) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise TypeError("dsn must be a non-empty string")
        self._dsn = dsn

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        psycopg = _get_psycopg()
        connection = await psycopg.AsyncConnection.connect(self._dsn)
        try:
            yield connection
        finally:
            await connection.close()

    async def _existing(self, event_id: str) -> StoredKajiEvent | None:
        async with self._connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT event_json FROM kaji_events WHERE event_id = %s",
                    (event_id,),
                )
            ).fetchone()
            return None if row is None else _decode_event(row[0])

    async def append(self, event: NewKajiEvent) -> AppendResult:
        draft = revalidate_new_event(event)
        try:
            async with self._connection() as connection:
                async with connection.transaction():
                    row = await (
                        await connection.execute(
                            """
                            INSERT INTO kaji_event_sequences (session_id, next_sequence)
                            VALUES (%s, 2)
                            ON CONFLICT (session_id)
                            DO UPDATE SET next_sequence = kaji_event_sequences.next_sequence + 1
                            RETURNING next_sequence - 1
                            """,
                            (draft.session_id,),
                        )
                    ).fetchone()
                    assert row is not None
                    stored = prepare_stored_event(draft, int(row[0]))
                    await connection.execute(
                        """
                        INSERT INTO kaji_events (session_id, sequence, event_id, event_json)
                        VALUES (%s, %s, %s, %s::jsonb)
                        """,
                        (
                            stored.session_id,
                            stored.sequence,
                            stored.id,
                            json.dumps(
                                stored.model_dump(mode="json"), separators=(",", ":")
                            ),
                        ),
                    )
                    return AppendResult(event=stored, inserted=True)
        except Exception as exc:
            if getattr(exc, "sqlstate", None) != "23505":
                raise
            existing = await self._existing(draft.id)
            if existing is not None and _draft_payload(existing) == _draft_payload(
                draft
            ):
                return AppendResult(event=existing, inserted=False)
            raise EventIdConflictError(draft.id) from exc

    async def get_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[StoredKajiEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if limit == 0:
            return []
        query = (
            "SELECT event_json FROM kaji_events "
            "WHERE session_id = %s AND sequence > %s ORDER BY sequence"
        )
        parameters: tuple[Any, ...] = (session_id, after_sequence)
        if limit is not None:
            query += " LIMIT %s"
            parameters += (limit,)
        async with self._connection() as connection:
            rows = await (await connection.execute(query, parameters)).fetchall()
        return [_decode_event(row[0]) for row in rows]

    async def last_sequence(self, session_id: str) -> int:
        async with self._connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT sequence FROM kaji_events
                    WHERE session_id = %s ORDER BY sequence DESC LIMIT 1
                    """,
                    (session_id,),
                )
            ).fetchone()
        return 0 if row is None else int(row[0])

    async def purge_session(self, session_id: str) -> bool:
        if not isinstance(session_id, str) or not session_id.strip():
            raise TypeError("session_id must be a non-empty string")
        async with self._connection() as connection:
            async with connection.transaction():
                deleted = await connection.execute(
                    "DELETE FROM kaji_events WHERE session_id = %s",
                    (session_id,),
                )
                await connection.execute(
                    "DELETE FROM kaji_event_sequences WHERE session_id = %s",
                    (session_id,),
                )
        return deleted.rowcount > 0
