"""Two-process crash/recovery proof for the durable Postgres seams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import os
from pathlib import Path
import sys
from typing import Any

import psycopg
from psycopg import sql
import pytest

from kaji.backends.postgres import PostgresToolIdempotencyLedger
from kaji.events.types import EventType

pytestmark = pytest.mark.skipif(
    not os.getenv("KAJI_POSTGRES_URL"),
    reason="KAJI_POSTGRES_URL is required for Postgres integration tests",
)

_SCHEMA = Path(__file__).parents[4] / "contracts" / "postgres" / "v1" / "schema.sql"


@pytest.fixture(autouse=True)
async def postgres_recovery_schema() -> AsyncIterator[None]:
    async with await psycopg.AsyncConnection.connect(
        os.environ["KAJI_POSTGRES_URL"]
    ) as connection:
        await connection.execute(
            "DROP TABLE IF EXISTS recovery_fixture_effects, kaji_event_sequences, "
            "kaji_events, kaji_tool_idempotency"
        )
        await connection.execute(sql.SQL(_SCHEMA.read_text()))
        await connection.execute(
            """
            CREATE TABLE recovery_fixture_effects (
                effect_key TEXT PRIMARY KEY,
                result_json JSONB NOT NULL
            )
            """
        )
        await connection.commit()
    yield


_PROCESS = r"""
import asyncio
import json
import os
import sys

import psycopg

from kaji.artifacts import ArtifactRef
from kaji.backends.postgres import PostgresEventCommitter, PostgresEventStore, PostgresToolIdempotencyLedger
from kaji.events.schemas import ArtifactEmitted, TaskCompleted, TaskCreated, TaskResumed, ToolCallCompleted, ToolCallFailed, ToolCallRequested, ToolCallStarted
from kaji.tasks import TaskState
from kaji.tasks.projector import project_task

config = json.loads(os.environ["KAJI_RECOVERY_CASE"])
dsn = os.environ["KAJI_POSTGRES_URL"]


async def fixture_capability():
    result = {"effect_key": config["effect_key"], "status": "external"}
    async with await psycopg.AsyncConnection.connect(dsn) as connection:
        await connection.execute(
            "INSERT INTO recovery_fixture_effects (effect_key, result_json) VALUES (%s, %s::jsonb)",
            (config["effect_key"], json.dumps(result, separators=(",", ":"))),
        )
        await connection.commit()
    return result


async def task_events(committer):
    values = {"session_id": config["session_id"], "task_id": config["task_id"]}
    await committer.commit(TaskCreated(id=f"{config['task_id']}-created", principal_id="fixture", input="mutate", **values))
    await committer.commit(TaskResumed(id=f"{config['task_id']}-running", **values))
    await committer.commit(ToolCallRequested(id=f"{config['task_id']}-requested", turn_id="turn", tool_name="fixture.mutate", tool_call_id="call", tool_args={"effect_key": config["effect_key"]}, session_id=config["session_id"]))


async def snapshot(store):
    return project_task(config["task_id"], await store.get_events(config["session_id"]))


async def main():
    action = config["action"]
    store = PostgresEventStore(dsn)
    committer = PostgresEventCommitter(store, poll_interval=0.001)
    ledger = PostgresToolIdempotencyLedger(dsn, poll_interval_seconds=0.001)
    claim_values = dict(session_id=config["session_id"], tool_call_id="call", tool_name="fixture.mutate", tool_args={"effect_key": config["effect_key"]})

    if action in {"crash_after_effect", "crash_before_handler"}:
        await task_events(committer)
        await committer.commit(ToolCallStarted(id=f"{config['task_id']}-started", turn_id="turn", tool_name="fixture.mutate", tool_call_id="call", session_id=config["session_id"]))
        claim = await ledger.claim(**claim_values)
        assert claim.kind == "owner"
        if action == "crash_after_effect":
            await ledger.mark_started(claim)
            await fixture_capability()
        print(json.dumps({"state": (await snapshot(store)).state.value}), flush=True)
        os._exit(23)

    if action == "inspect_started":
        assert (await snapshot(store)).state is TaskState.RUNNING
        claim = await ledger.claim(**claim_values)
        assert claim.kind == "waiter"
        assert await ledger.is_started(claim)
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            row = await (await connection.execute("SELECT count(*) FROM recovery_fixture_effects")).fetchone()
        assert row[0] == 1
        await committer.commit(ToolCallFailed(id=f"{config['task_id']}-unknown", turn_id="turn", tool_name="fixture.mutate", tool_call_id="call", error="process died after the durable start boundary", outcome="unknown", session_id=config["session_id"]))
        assert (await snapshot(store)).state is TaskState.RECONCILIATION_REQUIRED
        print(json.dumps({"state": (await snapshot(store)).state.value}), flush=True)
        return

    if action == "resume_reconciled":
        claim = await ledger.claim(**claim_values)
        assert claim.kind == "completed" and claim.resolution is not None
        result = claim.resolution.result
        await committer.commit(ToolCallCompleted(id=f"{config['task_id']}-reconciled", turn_id="turn", tool_name="fixture.mutate", tool_call_id="call", result=result, session_id=config["session_id"]))
        await committer.commit(ArtifactEmitted(id=f"{config['task_id']}-artifact", turn_id="turn", tool_call_id="call", artifact=ArtifactRef(id="fixture-effect", type="fixture/effect", uri=f"fixture://effects/{config['effect_key']}", metadata=result), session_id=config["session_id"]))
        await committer.commit(TaskResumed(id=f"{config['task_id']}-resumed", task_id=config["task_id"], session_id=config["session_id"]))
        await committer.commit(TaskCompleted(id=f"{config['task_id']}-completed", task_id=config["task_id"], session_id=config["session_id"]))
        assert (await snapshot(store)).state is TaskState.COMPLETED
        print(json.dumps({"state": (await snapshot(store)).state.value, "result": result}), flush=True)
        return

    if action == "retry_not_started":
        assert (await snapshot(store)).state is TaskState.RUNNING
        claim = await ledger.claim(**claim_values)
        assert claim.kind == "waiter"
        assert not await ledger.is_started(claim)
        assert await ledger.reconcile_release(config["session_id"], "call")
        retry = await ledger.claim(**claim_values)
        assert retry.kind == "owner"
        await ledger.mark_started(retry)
        result = await fixture_capability()
        await ledger.complete(retry, result)
        await committer.commit(ToolCallCompleted(id=f"{config['task_id']}-retried", turn_id="turn", tool_name="fixture.mutate", tool_call_id="call", result=result, session_id=config["session_id"]))
        await committer.commit(TaskCompleted(id=f"{config['task_id']}-completed", task_id=config["task_id"], session_id=config["session_id"]))
        assert (await snapshot(store)).state is TaskState.COMPLETED
        print(json.dumps({"state": (await snapshot(store)).state.value}), flush=True)
        return

    raise AssertionError(f"unknown action: {action}")


asyncio.run(main())
"""


async def _process(
    action: str, *, task_id: str, session_id: str, effect_key: str
) -> dict[str, Any]:
    environment = os.environ | {
        "KAJI_RECOVERY_CASE": json.dumps(
            {
                "action": action,
                "task_id": task_id,
                "session_id": session_id,
                "effect_key": effect_key,
            }
        )
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _PROCESS,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    stdout, stderr = await process.communicate()
    expected = 23 if action.startswith("crash_") else 0
    assert process.returncode == expected, stderr.decode()
    return json.loads(stdout)


async def _fixture_result(effect_key: str) -> dict[str, Any]:
    async with await psycopg.AsyncConnection.connect(
        os.environ["KAJI_POSTGRES_URL"]
    ) as connection:
        row = await (
            await connection.execute(
                "SELECT result_json FROM recovery_fixture_effects WHERE effect_key = %s",
                (effect_key,),
            )
        ).fetchone()
    assert row is not None
    return row[0]


async def _effect_count() -> int:
    async with await psycopg.AsyncConnection.connect(
        os.environ["KAJI_POSTGRES_URL"]
    ) as connection:
        row = await (
            await connection.execute("SELECT count(*) FROM recovery_fixture_effects")
        ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_restart_requires_reconciliation_after_started_external_effect() -> None:
    session_id, task_id, effect_key = (
        "recovery-session",
        "recovery-task",
        "recovery-effect",
    )

    assert (
        await _process(
            "crash_after_effect",
            task_id=task_id,
            session_id=session_id,
            effect_key=effect_key,
        )
    )["state"] == "running"
    assert (
        await _process(
            "inspect_started",
            task_id=task_id,
            session_id=session_id,
            effect_key=effect_key,
        )
    )["state"] == "reconciliation_required"
    assert await _effect_count() == 1

    reconciled = await _fixture_result(effect_key)
    ledger = PostgresToolIdempotencyLedger(os.environ["KAJI_POSTGRES_URL"])
    assert await ledger.reconcile_completed(session_id, "call", reconciled)

    resumed = await _process(
        "resume_reconciled",
        task_id=task_id,
        session_id=session_id,
        effect_key=effect_key,
    )
    assert resumed == {"state": "completed", "result": reconciled}
    assert await _effect_count() == 1

    from kaji.backends.postgres import PostgresEventStore

    events = await PostgresEventStore(os.environ["KAJI_POSTGRES_URL"]).get_events(
        session_id
    )
    assert [event.type for event in events] == [
        EventType.TASK_CREATED,
        EventType.TASK_RESUMED,
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_FAILED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.ARTIFACT_EMITTED,
        EventType.TASK_RESUMED,
        EventType.TASK_COMPLETED,
    ]
    assert events[-3].artifact.metadata == reconciled
    assert events[-4].result == reconciled


@pytest.mark.asyncio
async def test_restart_allows_retry_only_before_handler_start() -> None:
    session_id, task_id, effect_key = "retry-session", "retry-task", "retry-effect"

    assert (
        await _process(
            "crash_before_handler",
            task_id=task_id,
            session_id=session_id,
            effect_key=effect_key,
        )
    )["state"] == "running"
    assert (
        await _process(
            "retry_not_started",
            task_id=task_id,
            session_id=session_id,
            effect_key=effect_key,
        )
    )["state"] == "completed"
    assert await _effect_count() == 1

    from kaji.backends.postgres import PostgresEventStore

    events = await PostgresEventStore(os.environ["KAJI_POSTGRES_URL"]).get_events(
        session_id
    )
    assert EventType.TOOL_CALL_FAILED not in [event.type for event in events]
