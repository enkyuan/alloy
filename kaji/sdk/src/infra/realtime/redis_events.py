"""Compatibility exports for Redis realtime helper modules.

New code should import from the focused modules directly. This module preserves
the historical `kaji.infra.realtime.redis_events` surface for service callers
and downstream users.
"""

from kaji.infra.realtime.dedup import (
    claim_tool_call_execution,
    clear_tool_call_execution_in_progress,
    is_tool_call_execution_complete,
    is_tool_call_retry_safe,
    mark_tool_call_execution_complete,
    mark_tool_result_seen,
    tool_call_done_key,
    tool_call_in_progress_key,
    tool_result_seen_key,
)
from kaji.infra.realtime.dlq import (
    build_generic_dlq_entry,
    drain_generic_dlq,
    enqueue_generic_dlq,
    parse_generic_dlq_entry,
)
from kaji.infra.realtime.history_ops import (
    append_history,
    get_history,
    history_key,
)
from kaji.infra.realtime.publish import (
    drain_user_update_outbox,
    publish_user_update,
    publish_user_update_safely,
)
from kaji.infra.realtime.streams import run_stream_with_dlq

__all__ = [
    "append_history",
    "build_generic_dlq_entry",
    "claim_tool_call_execution",
    "clear_tool_call_execution_in_progress",
    "drain_generic_dlq",
    "drain_user_update_outbox",
    "enqueue_generic_dlq",
    "get_history",
    "history_key",
    "is_tool_call_execution_complete",
    "is_tool_call_retry_safe",
    "mark_tool_call_execution_complete",
    "mark_tool_result_seen",
    "parse_generic_dlq_entry",
    "publish_user_update",
    "publish_user_update_safely",
    "run_stream_with_dlq",
    "tool_call_done_key",
    "tool_call_in_progress_key",
    "tool_result_seen_key",
]
