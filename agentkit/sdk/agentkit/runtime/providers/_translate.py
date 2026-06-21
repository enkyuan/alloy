"""Shared role normalization and message formatting for all model providers.

Keeps role mapping and tool-message translation in one place so a fix
propagates everywhere instead of requiring a per-provider patch.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# Gemini uses "model" where every other provider uses "assistant".
_ALIASES: dict[str, str] = {
    "model": "assistant",
}

# The set of canonical roles the SDK uses internally.
_CANONICAL = {"user", "assistant", "tool", "system"}


def normalize_role(role: str) -> str:
    """Map a provider-specific role string to a canonical SDK role.

    Recognised aliases
    ------------------
    * ``"model"`` (Gemini) -> ``"assistant"``

    Unknown roles are returned unchanged so callers can decide how to handle
    them (log a warning, raise, or pass through to the provider).
    """
    return _ALIASES.get(role, role)


def to_gemini_role(role: str) -> str:
    """Map a canonical SDK role to Gemini's expected role string.

    Gemini expects ``"model"`` where the SDK uses ``"assistant"``.
    """
    canonical = normalize_role(role)
    if canonical == "assistant":
        return "model"
    return canonical


def format_messages_openai(
    messages: List[Dict[str, Any]],
    system_instruction: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Format the SDK's canonical message list for the OpenAI (and compatible) API.

    OpenAI requires tool results to be emitted as ``{"role": "tool",
    "content": str, "tool_call_id": str}`` messages. Assistant turns that
    requested tool calls must include ``tool_calls`` so the model can match
    results to their originating calls.

    This function uses the ``tool_call_id`` field added to tool messages by
    ``ReplaySession`` so that both the assistant request and the tool response
    are properly correlated in multi-turn conversations.
    """
    formatted: List[Dict[str, Any]] = []
    if system_instruction:
        formatted.append({"role": "system", "content": system_instruction})
    for msg in messages:
        role = normalize_role(msg["role"])
        if role == "tool":
            formatted.append(
                {
                    "role": "tool",
                    "content": msg.get("content", ""),
                    "tool_call_id": msg.get("tool_call_id") or msg.get("name", ""),
                }
            )
        else:
            formatted.append({"role": role, "content": msg.get("content", "")})
    return formatted


def format_messages_anthropic(
    messages: List[Dict[str, Any]],
    system_instruction: Optional[str] = None,
) -> tuple[Optional[str], List[Dict[str, Any]]]:
    """Format messages for the Anthropic Messages API.

    Anthropic requires:
    - System content as a top-level ``system`` string (not a message).
    - Tool results as ``{"role": "user", "content": [{"type": "tool_result",
      "tool_use_id": ..., "content": str}]}`` blocks.
    - Tool calls (from assistant) as ``{"role": "assistant", "content":
      [{"type": "tool_use", "id": ..., "name": ..., "input": ...}]}`` blocks.

    This correctly handles multi-turn tool loops without collapsing tool
    messages to assistant text.
    """
    system_parts: List[str] = []
    if system_instruction:
        system_parts.append(system_instruction)

    formatted: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("name", "")
            formatted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": content,
                        }
                    ],
                }
            )
        else:
            anthropic_role = "user" if role == "user" else "assistant"
            formatted.append({"role": anthropic_role, "content": content})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, formatted


def format_messages_gemini(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Format messages for the Gemini API (``contents`` list).

    Gemini uses ``"model"`` for assistant turns and expects tool results as
    ``functionResponse`` parts. Text content is wrapped in ``text`` parts.
    """
    contents: List[Dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "tool":
            tool_call_id = msg.get("tool_call_id") or msg.get("name", "")
            try:
                result_value = (
                    json.loads(content)
                    if isinstance(content, str) and content.startswith("{")
                    else content
                )
            except (json.JSONDecodeError, TypeError):
                result_value = content
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg.get("name", ""),
                                "id": tool_call_id,
                                "response": {"output": result_value},
                            }
                        }
                    ],
                }
            )
        else:
            gemini_role = to_gemini_role(role)
            contents.append({"role": gemini_role, "parts": [{"text": content}]})
    return contents
