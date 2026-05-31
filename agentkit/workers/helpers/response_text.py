"""Helpers for formatting user-facing responses from tool results."""

from __future__ import annotations

from agentkit.voice.event_models import ToolResult


def format_response_text(tool_result: ToolResult) -> str:
    """Convert a tool result into a concise assistant response string."""
    if tool_result.error:
        return f"Sorry, I couldn't complete that. {tool_result.error}"

    result_value = tool_result.result
    if result_value is None:
        return "Done."
    if not isinstance(result_value, dict):
        return "Done."
    result: dict[str, object] = result_value

    status = result.get("status")
    if isinstance(status, str) and status:
        return status

    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return message

    return "Done."
