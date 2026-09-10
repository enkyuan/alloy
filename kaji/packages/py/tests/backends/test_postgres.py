"""Integration coverage for the optional Postgres event adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import os
from pathlib import Path
import sys
from typing import LiteralString, cast
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from kaji.backends.postgres import (
    KajiPostgresBackend,
    PostgresEventCommitter,
    PostgresEventStore,
    PostgresToolIdempotencyLedger,
    PostgresTurnCoordinator,
    postgres_lock_key,
)
from kaji.events.errors import EventIdConflictError
from kaji.events.schemas import UserMessage
from kaji.runtime.tools.idempotency import (
    IdempotencyConflictError,
    ToolIdempotencyFailure,
    _fingerprint,
)

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
        await connection.execute(sql.SQL(cast(LiteralString, _SCHEMA.read_text())))
        await connection.commit()
    yield


def event(session_id: str, content: str, event_id: str | None = None) -> UserMessage:
    return UserMessage(
        id=event_id or str(uuid4()), session_id=session_id, content=content
    )


@pytest.mark.asyncio
async def test_postgres_backend_composes_matching_durable_seams() -> None:
    backend = KajiPostgresBackend(os.environ["KAJI_POSTGRES_URL"])
    assert backend.journal.store is backend.store
    assert isinstance(backend.idempotency_ledger, PostgresToolIdempotencyLedger)
    assert isinstance(backend.coordinator, PostgresTurnCoordinator)
    await backend.close()


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
async def test_postgres_tool_idempotency_is_durable_and_fail_closed() -> None:
    dsn = os.environ["KAJI_POSTGRES_URL"]
    first = PostgresToolIdempotencyLedger(dsn, poll_interval_seconds=0.001)
    second = PostgresToolIdempotencyLedger(dsn, poll_interval_seconds=0.001)
    kwargs = {"session_id": "ledger", "tool_call_id": "call", "tool_name": "echo", "tool_args": {"b": 2, "a": ["é", True]}}

    assert _fingerprint("echo", {"b": 2, "a": ["é", True]}) == "ea1cd9c7a8dd71948df4f2a3aeab8e3356ca6feec7bd5601e3e0ba23fd143d0d"
    owner = await first.claim(**kwargs)
    assert owner.kind == "owner"
    assert (await second.claim(**kwargs)).kind == "waiter"
    with pytest.raises(IdempotencyConflictError):
        await second.claim(
            session_id="ledger",
            tool_call_id="call",
            tool_name="echo",
            tool_args={"a": 3},
        )
    assert await first.is_started(owner) is False
    await first.mark_started(owner)
    assert await second.is_started(owner) is True
    await first.complete(owner, {"ok": True})
    completed = await second.claim(**kwargs)
    assert completed.kind == "completed"
    assert completed.resolution is not None and completed.resolution.result == {"ok": True}
    assert await second.release_completed("ledger") == 1

    retry = await first.claim(**kwargs)
    failure = ToolIdempotencyFailure("retry", "RETRY", True, "failed")
    await first.retryable_failure(retry, failure)
    assert (await second.claim(**kwargs)).kind == "owner"

    unknown = await first.claim(
        session_id="ledger", tool_call_id="unknown", tool_name="echo", tool_args={}
    )
    await first.unknown_outcome(
        unknown, ToolIdempotencyFailure("unknown", "UNKNOWN", False, "unknown")
    )
    assert (await second.claim(
        session_id="ledger", tool_call_id="unknown", tool_name="echo", tool_args={}
    )).kind == "unknown"
    assert await second.release_settled("ledger") == 1

    crashed = await first.claim(
        session_id="ledger", tool_call_id="crashed", tool_name="echo", tool_args={}
    )
    observed = await second.claim(
        session_id="ledger", tool_call_id="crashed", tool_name="echo", tool_args={}
    )
    assert crashed.kind == "owner" and observed.kind == "waiter"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(second.wait(observed), timeout=0.02)
    assert await second.reconcile_completed("ledger", "crashed", {"reconciled": True})
    assert (await second.claim(
        session_id="ledger", tool_call_id="crashed", tool_name="echo", tool_args={}
    )).kind == "completed"
    assert await second.release_completed("ledger") == 1

    release = await first.claim(
        session_id="ledger", tool_call_id="release", tool_name="echo", tool_args={}
    )
    assert release.kind == "owner"
    assert await second.reconcile_release("ledger", "release")
    assert (await second.claim(
        session_id="ledger", tool_call_id="release", tool_name="echo", tool_args={}
    )).kind == "owner"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_postgres_coordinator_serializes_cross_process_and_recovers() -> None:
    dsn = os.environ["KAJI_POSTGRES_URL"]
    first = PostgresTurnCoordinator(dsn, poll_interval_seconds=0.001)
    second = PostgresTurnCoordinator(dsn, poll_interval_seconds=0.001)
    assert postgres_lock_key("same") == 677529369334489940

    async with first.acquire("same"):
        waiting = second.acquire("same")
        waiter = asyncio.create_task(waiting.__aenter__())
        await asyncio.sleep(0.02)
        assert not waiter.done()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        left = await second.acquire("left").__aenter__()
        right = await second.acquire("right").__aenter__()
        await left.release()
        await right.release()

    later = await second.acquire("same").__aenter__()
    await later.release()

    script = """
import asyncio, os
from kaji.backends.postgres import PostgresTurnCoordinator
async def main():
    coordinator = PostgresTurnCoordinator(os.environ['KAJI_POSTGRES_URL'])
    async with coordinator.acquire('dead-holder'):
        print('held', flush=True)
        await asyncio.Event().wait()
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    assert process.stdout is not None
    assert await process.stdout.readline() == b"held\n"
    waiting = second.acquire("dead-holder")
    waiter = asyncio.create_task(waiting.__aenter__())
    await asyncio.sleep(0.02)
    assert not waiter.done()
    process.terminate()
    await process.wait()
    lease = await asyncio.wait_for(waiter, timeout=3)
    await lease.release()
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_postgres_coordinator_connection_failure_fails_closed() -> None:
    coordinator = PostgresTurnCoordinator(
        "postgresql://localhost:1/kaji?connect_timeout=1"
    )
    with pytest.raises(Exception):
        await asyncio.wait_for(coordinator.acquire("unavailable").__aenter__(), timeout=1)
    await coordinator.close()


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
