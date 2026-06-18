from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from agentkit.infra.events.schemas import (
    AgentKitEvent,
    EventType,
)


@dataclass
class SessionState:
    """A projection of the event log into current session state."""

    session_id: str
    is_active: bool = False
    messages: List[Dict[str, Any]] = field(default_factory=list)


def ReplaySession(events: Sequence[AgentKitEvent]) -> SessionState:
    """Reconstruct session state by replaying a sequence of events.

    The append-only event log is the source of truth.
    Session state is a projection of events.
    """
    if not events:
        raise ValueError("Cannot replay empty event log")

    state = SessionState(session_id=events[0].session_id)

    for event in sorted(events, key=lambda e: e.timestamp):
        if event.type == EventType.SESSION_CREATED:
            state.is_active = True
        elif event.type == EventType.SESSION_CLOSED:
            state.is_active = False
        elif event.type == EventType.USER_MESSAGE:
            state.messages.append({"role": "user", "content": event.content})
        elif event.type == EventType.AGENT_MESSAGE_COMPLETED:
            state.messages.append({"role": "assistant", "content": event.content})
        elif event.type == EventType.TRANSCRIPT_FINAL:
            # For voice sessions, final transcript acts as a user message
            state.messages.append({"role": "user", "content": event.text})
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
