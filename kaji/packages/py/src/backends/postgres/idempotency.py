"""Postgres implementation of the durable tool idempotency ledger."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from typing import Any, Literal, cast
import uuid

from kaji.events.json import durable_json_snapshot
from kaji.events.schemas import MAX_DURABLE_TOOL_RESULT_BYTES
from kaji.runtime.tools.idempotency import (
    IdempotencyConflictError,
    ToolIdempotencyClaim,
    ToolIdempotencyFailure,
    ToolIdempotencyResolution,
    _fingerprint,
)


def _get_psycopg() -> Any:
    try:
        import psycopg  # noqa: PLC0415

        return psycopg
    except ImportError as exc:
        raise ImportError(
            "Postgres support requires `pip install 'kaji[postgres]'`."
        ) from exc


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _failure_json(failure: ToolIdempotencyFailure) -> dict[str, Any]:
    result: dict[str, Any] = {
        "error": failure.error,
        "error_code": failure.error_code,
        "retryable": failure.retryable,
        "outcome": failure.outcome,
    }
    for key in ("subject", "reason_code", "recovery_code", "doc_url"):
        value = getattr(failure, key)
        if value is not None:
            result[key] = value
    return result


def _failure(value: Any) -> ToolIdempotencyFailure:
    data = _decode_json(value)
    if not isinstance(data, dict):
        return _ambiguous_failure()
    try:
        outcome = data["outcome"]
        if outcome not in {"not_started", "failed", "unknown"}:
            raise ValueError
        return ToolIdempotencyFailure(
            error=str(data["error"]),
            error_code=str(data["error_code"]),
            retryable=bool(data["retryable"]),
            outcome=cast(Literal["not_started", "failed", "unknown"], outcome),
            subject=data.get("subject"),
            reason_code=data.get("reason_code"),
            recovery_code=data.get("recovery_code"),
            doc_url=data.get("doc_url"),
        )
    except (KeyError, ValueError, TypeError):
        return _ambiguous_failure()


def _ambiguous_failure() -> ToolIdempotencyFailure:
    return ToolIdempotencyFailure(
        error="Tool execution outcome is unknown",
        error_code="TOOL_EXECUTION_UNKNOWN",
        retryable=False,
        outcome="unknown",
    )


@dataclass(slots=True)
class _LocalRunning:
    future: asyncio.Future[ToolIdempotencyResolution]
    started: bool = False


class PostgresToolIdempotencyLedger:
    """Durable, fail-closed tool claims backed by ``kaji_tool_idempotency``.

    A surviving ``running`` row is deliberately never reclaimed automatically.
    Use ``reconcile_completed`` or ``reconcile_release`` after an operator has
    established the external side effect's outcome.
    """

    def __init__(self, dsn: str, *, poll_interval_seconds: float = 0.05) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise TypeError("dsn must be a non-empty string")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._dsn = dsn
        self._poll_interval_seconds = poll_interval_seconds
        self._running: dict[str, _LocalRunning] = {}

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        connection = await _get_psycopg().AsyncConnection.connect(self._dsn)
        try:
            yield connection
        finally:
            await connection.close()

    async def claim(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> ToolIdempotencyClaim:
        fingerprint = _fingerprint(tool_name, tool_args)
        token = uuid.uuid4().hex
        while True:
            async with self._connection() as connection:
                async with connection.transaction():
                    inserted = await (
                        await connection.execute(
                            """
                            INSERT INTO kaji_tool_idempotency
                                (session_id, tool_call_id, fingerprint, status, claim_token)
                            VALUES (%s, %s, %s, 'running', %s)
                            ON CONFLICT (session_id, tool_call_id) DO NOTHING
                            RETURNING claim_token
                            """,
                            (session_id, tool_call_id, fingerprint, token),
                        )
                    ).fetchone()
                    if inserted is not None:
                        self._running[token] = _LocalRunning(
                            asyncio.get_running_loop().create_future()
                        )
                        return ToolIdempotencyClaim(
                            kind="owner",
                            session_id=session_id,
                            tool_call_id=tool_call_id,
                            claim_token=token,
                        )
                    row = await (
                        await connection.execute(
                            """
                            SELECT fingerprint, status, claim_token, result_json, error_json
                            FROM kaji_tool_idempotency
                            WHERE session_id = %s AND tool_call_id = %s
                            """,
                            (session_id, tool_call_id),
                        )
                    ).fetchone()
            if row is None:
                continue
            if row[0] != fingerprint:
                raise IdempotencyConflictError(
                    "tool call idempotency key conflicts with an existing invocation"
                )
            status = row[1]
            if status == "running":
                return ToolIdempotencyClaim(
                    kind="waiter",
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    claim_token=row[2],
                )
            if status == "completed":
                return ToolIdempotencyClaim(
                    kind="completed",
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    claim_token=row[2],
                    resolution=ToolIdempotencyResolution(result=_decode_json(row[3])),
                )
            return ToolIdempotencyClaim(
                kind="unknown",
                session_id=session_id,
                tool_call_id=tool_call_id,
                claim_token=row[2],
                resolution=ToolIdempotencyResolution(failure=_failure(row[4])),
            )

    async def wait(self, claim: ToolIdempotencyClaim) -> ToolIdempotencyResolution:
        if claim.kind != "waiter":
            if claim.resolution is None:
                raise RuntimeError("only a waiter claim can be awaited")
            return claim.resolution
        local = self._running.get(str(claim.claim_token))
        if local is not None:
            return await asyncio.shield(local.future)
        while True:
            async with self._connection() as connection:
                row = await (
                    await connection.execute(
                        """
                        SELECT status, result_json, error_json FROM kaji_tool_idempotency
                        WHERE session_id = %s AND tool_call_id = %s AND claim_token = %s
                        """,
                        (claim.session_id, claim.tool_call_id, claim.claim_token),
                    )
                ).fetchone()
            if row is None:
                return ToolIdempotencyResolution(failure=_ambiguous_failure())
            if row[0] == "completed":
                return ToolIdempotencyResolution(result=_decode_json(row[1]))
            if row[0] == "unknown":
                return ToolIdempotencyResolution(failure=_failure(row[2]))
            await asyncio.sleep(self._poll_interval_seconds)

    async def is_started(self, claim: ToolIdempotencyClaim) -> bool:
        async with self._connection() as connection:
            row = await (
                await connection.execute(
                    """
                    SELECT started_at IS NOT NULL FROM kaji_tool_idempotency
                    WHERE session_id = %s AND tool_call_id = %s AND claim_token = %s
                    """,
                    (claim.session_id, claim.tool_call_id, claim.claim_token),
                )
            ).fetchone()
        return row is None or bool(row[0])

    async def mark_started(self, claim: ToolIdempotencyClaim) -> None:
        await self._transition(claim, "UPDATE kaji_tool_idempotency SET started_at = CURRENT_TIMESTAMP")
        local = self._running.get(str(claim.claim_token))
        if local is not None:
            local.started = True

    async def complete(self, claim: ToolIdempotencyClaim, result: Any) -> None:
        detached = durable_json_snapshot(
            result, subject="tool_result", max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES
        )
        await self._transition(
            claim,
            "UPDATE kaji_tool_idempotency SET status = 'completed', result_json = %s::jsonb, error_json = NULL, updated_at = CURRENT_TIMESTAMP",
            (_json(detached),),
        )
        self._settle_local(claim, ToolIdempotencyResolution(result=detached))

    async def retryable_failure(
        self, claim: ToolIdempotencyClaim, failure: ToolIdempotencyFailure
    ) -> None:
        await self._transition(claim, "DELETE FROM kaji_tool_idempotency")
        self._settle_local(claim, ToolIdempotencyResolution(failure=failure))

    async def unknown_outcome(
        self, claim: ToolIdempotencyClaim, failure: ToolIdempotencyFailure
    ) -> None:
        await self._transition(
            claim,
            "UPDATE kaji_tool_idempotency SET status = 'unknown', error_json = %s::jsonb, result_json = NULL, updated_at = CURRENT_TIMESTAMP",
            (_json(_failure_json(failure)),),
        )
        self._settle_local(claim, ToolIdempotencyResolution(failure=failure))

    async def release_completed(self, session_id: str) -> int:
        return await self._release(session_id, "status = 'completed'")

    async def release_settled(self, session_id: str) -> int:
        return await self._release(session_id, "status <> 'running'")

    async def reconcile_completed(self, session_id: str, tool_call_id: str, result: Any) -> bool:
        detached = durable_json_snapshot(
            result, subject="tool_result", max_bytes=MAX_DURABLE_TOOL_RESULT_BYTES
        )
        async with self._connection() as connection:
            updated = await connection.execute(
                """
                UPDATE kaji_tool_idempotency
                SET status = 'completed', result_json = %s::jsonb, error_json = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE session_id = %s AND tool_call_id = %s AND status = 'running'
                """,
                (_json(detached), session_id, tool_call_id),
            )
            await connection.commit()
        return updated.rowcount == 1

    async def reconcile_release(self, session_id: str, tool_call_id: str) -> bool:
        async with self._connection() as connection:
            deleted = await connection.execute(
                """
                DELETE FROM kaji_tool_idempotency
                WHERE session_id = %s AND tool_call_id = %s AND status = 'running'
                """,
                (session_id, tool_call_id),
            )
            await connection.commit()
        return deleted.rowcount == 1

    async def _transition(
        self, claim: ToolIdempotencyClaim, statement: str, values: tuple[Any, ...] = ()
    ) -> None:
        if claim.kind != "owner":
            raise ValueError("ledger transition requires an owner claim")
        async with self._connection() as connection:
            updated = await connection.execute(
                f"{statement} WHERE session_id = %s AND tool_call_id = %s "
                "AND claim_token = %s AND status = 'running'",
                (*values, claim.session_id, claim.tool_call_id, claim.claim_token),
            )
            await connection.commit()
        if updated.rowcount != 1:
            raise RuntimeError("idempotency claim is no longer running")

    async def _release(self, session_id: str, condition: str) -> int:
        async with self._connection() as connection:
            deleted = await connection.execute(
                f"DELETE FROM kaji_tool_idempotency WHERE session_id = %s AND {condition}",
                (session_id,),
            )
            await connection.commit()
        return deleted.rowcount

    def _settle_local(
        self, claim: ToolIdempotencyClaim, resolution: ToolIdempotencyResolution
    ) -> None:
        local = self._running.pop(str(claim.claim_token), None)
        if local is not None and not local.future.done():
            local.future.set_result(resolution)
