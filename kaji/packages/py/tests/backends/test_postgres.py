"""Integration coverage for the optional Postgres event adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from kaji.backends.postgres import PostgresEventCommitter, PostgresEventStore
from kaji.events.errors import EventIdConflictError
from kaji.events.schemas import UserMessage

pytestmark = pytest.mark.skipif(
    not os.getenv("KAJI_POSTGRES_URL"),
    reason="KAJI_POSTGRES_URL is required for Postgres integration tests",
)

_SCHEMA = Path(__file__).parents[4] / "contracts" / "postgres" / "v1" / "schema.sql"


@pytest.fixture(autouse=True)
async def postgres_schema() -> AsyncIterator[None]:
    async with await psycopg.AsyncConnection.connect(
        os.environ["KAJI_POSTGRES_URL"]
    ) as connection:
        await connection.execute(
            "DROP TABLE IF EXISTS kaji_event_sequences, kaji_events, kaji_tool_idempotency"
        )
        await connection.execute(sql.SQL(_SCHEMA.read_text()))
        await connection.commit()
    yield


def event(session_id: str, content: str, event_id: str | None = None) -> UserMessage:
    return UserMessage(
        id=event_id or str(uuid4()), session_id=session_id, content=content
    )


@pytest.mark.asyncio
async def test_postgres_append_duplicate_cursor_rollback_and_purge() -> None:
    store = PostgresEventStore(os.environ["KAJI_POSTGRES_URL"])
    first_event = event("one", "first", "one")
    first = await store.append(first_event)
    assert first.inserted and first.event.sequence == 1
    assert (await store.append(first_event)).inserted is False
    with pytest.raises(EventIdConflictError):
        await store.append(event("one", "different", "one"))
    second = await store.append(event("one", "second", "two"))
    assert second.event.sequence == 2
    assert [
        item.sequence for item in await store.get_events("one", after_sequence=1)
    ] == [2]
    assert await store.purge_session("one") is True
    assert await store.last_sequence("one") == 0


@pytest.mark.asyncio
async def test_postgres_sequences_are_contiguous_per_session_and_independent() -> None:
    store = PostgresEventStore(os.environ["KAJI_POSTGRES_URL"])
    same = await asyncio.gather(
        *(store.append(event("same", str(index))) for index in range(20))
    )
    assert sorted(result.event.sequence for result in same) == list(range(1, 21))

    left, right = await asyncio.gather(
        asyncio.gather(
            *(store.append(event("left", str(index))) for index in range(10))
        ),
        asyncio.gather(
            *(store.append(event("right", str(index))) for index in range(10))
        ),
    )
    assert sorted(result.event.sequence for result in left) == list(range(1, 11))
    assert sorted(result.event.sequence for result in right) == list(range(1, 11))


@pytest.mark.asyncio
async def test_postgres_reconnect_and_committer_subscription() -> None:
    dsn = os.environ["KAJI_POSTGRES_URL"]
    first = PostgresEventStore(dsn)
    await first.append(event("reconnect", "first", "reconnect-one"))
    second = PostgresEventStore(dsn)
    committer = PostgresEventCommitter(second, poll_interval=0.001)
    subscription = await committer.open_subscription("reconnect")
    assert (await anext(subscription)).id == "reconnect-one"
    await committer.commit(event("reconnect", "second", "reconnect-two"))
    assert (await anext(subscription)).id == "reconnect-two"
    await subscription.aclose()
