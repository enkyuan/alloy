"""Tool call idempotency — prevents duplicate side effects."""

from __future__ import annotations

from typing import Any

from agentkit.runtime.workflows.idempotency import (
    IdempotencyStore,
    build_idempotency_key,
)


def build_tool_idempotency_key(
    *, session_id: str, tool_name: str, tool_args: dict[str, Any]
) -> str:
    return build_idempotency_key(
        workflow=f"tool:{session_id}:{tool_name}",
        payload=tool_args,
    )


class ToolIdempotencyGuard:
    """Tracks tool invocations per session to skip duplicate executions."""

    def __init__(self) -> None:
        self._store = IdempotencyStore()

    def should_execute(
        self, *, session_id: str, tool_name: str, tool_args: dict[str, Any]
    ) -> bool:
        key = build_tool_idempotency_key(
            session_id=session_id, tool_name=tool_name, tool_args=tool_args
        )
        return self._store.claim(key)
