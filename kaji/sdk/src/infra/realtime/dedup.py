"""Redis keys and helpers for tool-result/tool-call idempotency."""

from __future__ import annotations

from typing import Any

from kaji.infra.realtime.redis import RedisConfig, RedisKeys


def tool_result_seen_key(tool_call_id: str) -> str:
    return f"{RedisKeys.TOOL_RESULT_SEEN_KEY_PREFIX}{tool_call_id}"


def tool_call_in_progress_key(tool_call_id: str) -> str:
    return f"{RedisKeys.TOOL_CALL_DEDUP_IN_PROGRESS_PREFIX}{tool_call_id}"


def tool_call_done_key(tool_call_id: str) -> str:
    return f"{RedisKeys.TOOL_CALL_DEDUP_DONE_PREFIX}{tool_call_id}"


def is_tool_call_retry_safe(tool_name: str) -> bool:
    return tool_name in RedisConfig.TOOL_CALL_RETRYABLE_TOOL_NAMES


async def mark_tool_result_seen(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return False
    return bool(
        await redis.set(
            tool_result_seen_key(tool_call_id),
            "1",
            ex=RedisConfig.TOOL_RESULT_SEEN_TTL_SECONDS,
            nx=True,
        )
    )


async def claim_tool_call_execution(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return True
    return bool(
        await redis.set(
            tool_call_in_progress_key(tool_call_id),
            "1",
            ex=RedisConfig.TOOL_CALL_DEDUP_IN_PROGRESS_TTL_SECONDS,
            nx=True,
        )
    )


async def is_tool_call_execution_complete(redis: Any, *, tool_call_id: str) -> bool:
    if not tool_call_id:
        return False
    return bool(await redis.get(tool_call_done_key(tool_call_id)))


async def mark_tool_call_execution_complete(redis: Any, *, tool_call_id: str) -> None:
    if not tool_call_id:
        return
    done_key = tool_call_done_key(tool_call_id)
    progress_key = tool_call_in_progress_key(tool_call_id)
    await redis.set(done_key, "1", ex=RedisConfig.TOOL_CALL_DEDUP_TTL_SECONDS)
    await redis.delete(progress_key)


async def clear_tool_call_execution_in_progress(
    redis: Any, *, tool_call_id: str
) -> None:
    if not tool_call_id:
        return
    await redis.delete(tool_call_in_progress_key(tool_call_id))
