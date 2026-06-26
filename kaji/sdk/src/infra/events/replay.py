from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from kaji.infra.events.schemas import (
    KajiEvent,
    EventType,
)


@dataclass
class SessionState:
    """A projection of the event log into current session state."""

    session_id: str
    is_active: bool = False
    messages: List[Dict[str, Any]] = field(default_factory=list)


def replay_session(events: Sequence[KajiEvent]) -> SessionState:
    """Reconstruct session state by replaying a sequence of events.

    The append-only event log is the source of truth. Events from
    ``EventStore`` arrive in append order; out-of-order inputs (e.g.
    constructed in tests) are sorted on the fly.

    ``TOOL_CALL_REQUESTED`` events are attached to the most recent
    ``assistant`` message as ``tool_calls`` entries so the projected history
    carries the assistant-side request alongside the eventual tool response.
    OpenAI and Anthropic both reject ``role: tool`` messages whose originating
    assistant turn doesn't reference the matching call id.
    """
    if not events:
        raise ValueError("Cannot replay empty event log")

    state = SessionState(session_id=events[0].session_id)
    ordered: Iterable[KajiEvent] = events
    if any(
        events[i].timestamp < events[i - 1].timestamp for i in range(1, len(events))
    ):
        ordered = sorted(events, key=lambda e: e.timestamp)

    last_assistant: Optional[Dict[str, Any]] = None

    for event in ordered:
        if event.type == EventType.SESSION_CREATED:
            state.is_active = True
        elif event.type == EventType.SESSION_CLOSED:
            state.is_active = False
        elif event.type == EventType.USER_MESSAGE:
            state.messages.append({"role": "user", "content": event.content})
            last_assistant = None
        elif event.type == EventType.AGENT_MESSAGE_COMPLETED:
            msg: Dict[str, Any] = {"role": "assistant", "content": event.content}
            state.messages.append(msg)
            last_assistant = msg
        elif event.type == EventType.TRANSCRIPT_FINAL:
            # For voice sessions, final transcript acts as a user message
            state.messages.append({"role": "user", "content": event.text})
            last_assistant = None
        elif event.type == EventType.TOOL_CALL_REQUESTED:
            # Synthesise an assistant turn when the model produced tool calls
            # with no text — otherwise the next role:tool message has no
            # parent assistant turn to reference its tool_call_id.
            if last_assistant is None:
                last_assistant = {"role": "assistant", "content": "", "tool_calls": []}
                state.messages.append(last_assistant)
            last_assistant.setdefault("tool_calls", []).append(
                {
                    "id": event.tool_call_id,
                    "name": event.tool_name,
                    "arguments": event.tool_args,
                }
            )
        elif event.type == EventType.TOOL_CALL_COMPLETED:
            state.messages.append(
                {
                    "role": "tool",
                    "name": event.tool_name,
                    "content": str(event.result),
                    "tool_call_id": event.tool_call_id,
                }
            )
        elif event.type == EventType.TOOL_CALL_FAILED:
            # Record the failure as a tool message too, so the agent loop sees
            # the error in history and can react, instead of re-requesting the
            # same tool every iteration until it hits max_iterations.
            state.messages.append(
                {
                    "role": "tool",
                    "name": event.tool_name,
                    "content": f"Error: {event.error}",
                    "tool_call_id": event.tool_call_id,
                }
            )

    return state
