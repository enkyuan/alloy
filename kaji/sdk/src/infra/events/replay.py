from dataclasses import dataclass, field
import warnings
from typing import Any, Dict, Iterable, List, Optional, Sequence

from kaji.infra.events.schemas import (
    EventType,
    KajiEvent,
    StoredKajiEvent,
    require_stored_event,
)


@dataclass
class SessionState:
    """A projection of the event log into current session state."""

    session_id: str
    is_active: bool = False
    messages: List[Dict[str, Any]] = field(default_factory=list)


class LegacyEventOrderingWarning(UserWarning):
    """A fully legacy event log was ordered by timestamp compatibility rules."""


def _legacy_timestamp_order(events: Sequence[KajiEvent]) -> list[KajiEvent]:
    warnings.warn(
        "replaying a legacy unsequenced event log; timestamp ordering is deprecated",
        LegacyEventOrderingWarning,
        stacklevel=2,
    )
    return [
        event
        for _, event in sorted(
            enumerate(events),
            key=lambda item: (item[1].timestamp, item[0]),
        )
    ]


def _session_id(events: Sequence[KajiEvent | StoredKajiEvent]) -> str:
    if not events:
        raise ValueError("Cannot replay empty event log")
    session_id = events[0].session_id
    if any(event.session_id != session_id for event in events[1:]):
        raise ValueError("Cannot replay events from mixed sessions")
    return session_id


def replay_session(events: Sequence[StoredKajiEvent]) -> SessionState:
    """Reconstruct state from strictly sequenced persisted events.

    Fully unsequenced historical logs must opt into ``replay_legacy_session``.

    ``TOOL_CALL_REQUESTED`` events are attached to the most recent
    ``assistant`` message as ``tool_calls`` entries so the projected history
    carries the assistant-side request alongside the eventual tool response.
    OpenAI and Anthropic both reject ``role: tool`` messages whose originating
    assistant turn doesn't reference the matching call id.
    """
    session_id = _session_id(events)
    raw_sequences = [getattr(event, "sequence", None) for event in events]
    if any(sequence is None for sequence in raw_sequences) and any(
        sequence is not None for sequence in raw_sequences
    ):
        raise ValueError("Cannot replay mixed sequenced and unsequenced events")
    ordered = [require_stored_event(event) for event in events]
    sequences = [event.sequence for event in ordered]
    if len(sequences) != len(set(sequences)):
        raise ValueError("Cannot replay duplicate event sequences")
    if any(current <= previous for previous, current in zip(sequences, sequences[1:])):
        raise ValueError("Cannot replay non-monotonic event sequences")
    return _project_session(ordered, session_id=session_id)


def replay_legacy_session(events: Sequence[KajiEvent]) -> SessionState:
    """Replay a fully unsequenced legacy log with a visible warning."""
    session_id = _session_id(events)
    if any(event.sequence is not None for event in events):
        raise ValueError("Legacy replay accepts only fully unsequenced event logs")
    return _project_session(
        _legacy_timestamp_order(events),
        session_id=session_id,
    )


def _project_session(
    events: Iterable[KajiEvent | StoredKajiEvent],
    *,
    session_id: str,
) -> SessionState:
    state = SessionState(session_id=session_id)

    last_assistant: Optional[Dict[str, Any]] = None

    for event in events:
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
