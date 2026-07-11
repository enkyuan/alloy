from dataclasses import dataclass, field
from copy import deepcopy
import warnings
from typing import Any, Dict, List, Optional, Sequence

from kaji.infra.events.schemas import (
    EventType,
    KajiEvent,
    StoredKajiEvent,
    require_stored_event,
    revalidate_new_event,
    revalidate_stored_event,
)
from kaji.infra.events.json import canonical_json
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)


@dataclass(frozen=True, slots=True)
class ApprovalKey:
    """Security and correlation key for one tool approval request."""

    turn_id: str
    tool_call_id: str
    tool_name: str


@dataclass
class SessionState:
    """A projection of the event log into current session state."""

    session_id: str
    is_active: bool = False
    messages: List[Dict[str, Any]] = field(default_factory=list)
    pending_approvals: set[ApprovalKey] = field(default_factory=set)
    approved_approvals: set[ApprovalKey] = field(default_factory=set)
    rejected_approvals: dict[ApprovalKey, str] = field(default_factory=dict)
    _last_assistant_index: Optional[int] = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )


class LegacyEventOrderingWarning(UserWarning):
    """A fully legacy event log was ordered by timestamp compatibility rules."""


def _canonical_replay_json(value: Any) -> str:
    """Serialize a JSON value with the cross-SDK replay policy.

    Lists retain their order, object keys use UTF-16 lexical order, strings
    retain Unicode text, and numbers use the finite IEEE-754 domain with
    ECMAScript's shortest round-trip spelling and fixed/exponent boundaries.
    Python integers must round-trip through that number domain exactly.
    Unsupported values, including tuples, fail instead of being coerced.
    """
    return canonical_json(value, subject="tool result")


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


def replay_session(
    events: Sequence[StoredKajiEvent],
    *,
    metrics_sink: MetricsSink = NOOP_METRICS,
) -> SessionState:
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
    ordered = [revalidate_stored_event(event) for event in events]
    record_metric(metrics_sink, "kaji.replay.input_events", len(ordered))
    sequences = [event.sequence for event in ordered]
    if len(sequences) != len(set(sequences)):
        raise ValueError("Cannot replay duplicate event sequences")
    if any(current <= previous for previous, current in zip(sequences, sequences[1:])):
        raise ValueError("Cannot replay non-monotonic event sequences")
    state = SessionState(session_id=session_id)
    for event in ordered:
        apply_event(state, event)
    return state


def replay_legacy_session(
    events: Sequence[KajiEvent],
    *,
    metrics_sink: MetricsSink = NOOP_METRICS,
) -> SessionState:
    """Replay a fully unsequenced legacy log with a visible warning."""
    session_id = _session_id(events)
    if any(event.sequence is not None for event in events):
        raise ValueError("Legacy replay accepts only fully unsequenced event logs")
    validated = [revalidate_new_event(event) for event in events]
    state = SessionState(session_id=session_id)
    record_metric(metrics_sink, "kaji.replay.input_events", len(validated))
    for event in _legacy_timestamp_order(validated):
        _apply_event(state, event)
    return state


def apply_event(state: SessionState, event: StoredKajiEvent) -> None:
    """Apply one persisted event to an existing session projection in place."""
    stored = require_stored_event(event)
    if stored.session_id != state.session_id:
        raise ValueError("Cannot project events from mixed sessions")
    _apply_event(state, stored)


def _apply_event(state: SessionState, event: KajiEvent | StoredKajiEvent) -> None:
    if event.type == EventType.SESSION_CREATED:
        state.is_active = True
    elif event.type == EventType.SESSION_CLOSED:
        state.is_active = False
    elif event.type == EventType.AGENT_REASONING_STARTED:
        # Each reasoning event begins one provider-output batch. Parallel tool
        # requests after it share an assistant message; the next batch does not.
        state._last_assistant_index = None
    elif event.type == EventType.USER_MESSAGE:
        state.messages.append({"role": "user", "content": event.content})
        state._last_assistant_index = None
    elif event.type == EventType.AGENT_MESSAGE_COMPLETED:
        state.messages.append({"role": "assistant", "content": event.content})
        state._last_assistant_index = len(state.messages) - 1
    elif event.type == EventType.TRANSCRIPT_FINAL:
        # For voice sessions, final transcript acts as a user message.
        state.messages.append({"role": "user", "content": event.text})
        state._last_assistant_index = None
    elif event.type == EventType.TOOL_CALL_REQUESTED:
        # Synthesise an assistant turn when the model produced tool calls with
        # no text. Retaining its index makes repeated one-event application O(1).
        if state._last_assistant_index is None:
            state.messages.append(
                {"role": "assistant", "content": "", "tool_calls": []}
            )
            state._last_assistant_index = len(state.messages) - 1
        last_assistant = state.messages[state._last_assistant_index]
        last_assistant.setdefault("tool_calls", []).append(
            {
                "id": event.tool_call_id,
                "name": event.tool_name,
                "arguments": deepcopy(event.tool_args),
            }
        )
    elif event.type == EventType.TOOL_APPROVAL_REQUESTED:
        assert event.turn_id is not None
        state.pending_approvals.add(
            ApprovalKey(
                turn_id=event.turn_id,
                tool_call_id=event.tool_call_id,
                tool_name=event.tool_name,
            )
        )
    elif event.type == EventType.TOOL_APPROVAL_APPROVED:
        assert event.turn_id is not None
        approval = ApprovalKey(
            turn_id=event.turn_id,
            tool_call_id=event.tool_call_id,
            tool_name=event.tool_name,
        )
        if approval in state.pending_approvals:
            state.pending_approvals.remove(approval)
            state.approved_approvals.add(approval)
    elif event.type == EventType.TOOL_APPROVAL_REJECTED:
        assert event.turn_id is not None
        approval = ApprovalKey(
            turn_id=event.turn_id,
            tool_call_id=event.tool_call_id,
            tool_name=event.tool_name,
        )
        if approval in state.pending_approvals:
            state.pending_approvals.remove(approval)
            state.rejected_approvals[approval] = event.error_code
    elif event.type == EventType.TOOL_CALL_COMPLETED:
        content = _canonical_replay_json(event.result)
        state.messages.append(
            {
                "role": "tool",
                "name": event.tool_name,
                "content": content,
                "tool_call_id": event.tool_call_id,
            }
        )
    elif event.type == EventType.TOOL_CALL_FAILED:
        if event.turn_id is not None:
            state.pending_approvals.discard(
                ApprovalKey(
                    turn_id=event.turn_id,
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                )
            )
        # Keep failures in provider history so the model can react instead of
        # repeating the same call until max_iterations.
        state.messages.append(
            {
                "role": "tool",
                "name": event.tool_name,
                "content": f"Error: {event.error}",
                "tool_call_id": event.tool_call_id,
            }
        )
