from dataclasses import dataclass, field
from copy import deepcopy
import json
import math
import warnings
from typing import Any, Dict, List, Optional, Sequence

from kaji.infra.events.schemas import (
    EventType,
    KajiEvent,
    StoredKajiEvent,
    require_stored_event,
)
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


def _canonical_float(value: float) -> str:
    """Render one finite IEEE-754 value with ECMAScript JSON number spelling."""
    if not math.isfinite(value):
        raise ValueError("tool result contains a non-finite number")
    if value == 0:
        return "0"

    source = repr(abs(value)).lower()
    coefficient, marker, raw_exponent = source.partition("e")
    exponent = int(raw_exponent) if marker else 0
    whole, point, fraction = coefficient.partition(".")
    digits = (whole + fraction).lstrip("0")
    scale = exponent - (len(fraction) if point else 0)
    while digits.endswith("0"):
        digits = digits[:-1]
        scale += 1

    decimal_exponent = len(digits) + scale - 1
    sign = "-" if value < 0 else ""
    if -6 <= decimal_exponent < 21:
        decimal_point = decimal_exponent + 1
        if decimal_point <= 0:
            body = "0." + ("0" * -decimal_point) + digits
        elif decimal_point >= len(digits):
            body = digits + ("0" * (decimal_point - len(digits)))
        else:
            body = digits[:decimal_point] + "." + digits[decimal_point:]
        return sign + body

    mantissa = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
    exponent_sign = "+" if decimal_exponent >= 0 else ""
    return f"{sign}{mantissa}e{exponent_sign}{decimal_exponent}"


def _utf16_sort_key(value: str) -> bytes:
    """Match ECMAScript's lexicographic UTF-16 object-key ordering."""
    return value.encode("utf-16-be", errors="surrogatepass")


def _canonical_integer(value: int) -> str:
    """Render an integer only when the shared IEEE-754 number domain preserves it."""
    try:
        number = float(value)
    except OverflowError as error:
        raise TypeError(
            "tool result integer is not exactly representable as a finite IEEE-754 number"
        ) from error
    if not math.isfinite(number) or int(number) != value:
        raise TypeError(
            "tool result integer is not exactly representable as a finite IEEE-754 number"
        )
    return _canonical_float(number)


def _canonical_replay_json(value: Any) -> str:
    """Serialize a JSON value with the cross-SDK replay policy.

    Lists retain their order, object keys use UTF-16 lexical order, strings
    retain Unicode text, and numbers use the finite IEEE-754 domain with
    ECMAScript's shortest round-trip spelling and fixed/exponent boundaries.
    Python integers must round-trip through that number domain exactly.
    Unsupported values, including tuples, fail instead of being coerced.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return _canonical_integer(value)
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical_replay_json(item) for item in value) + "]"
    if isinstance(value, dict):
        keys: list[str] = []
        for key in value:
            if not isinstance(key, str):
                raise TypeError("tool result JSON object keys must be strings")
            keys.append(key)
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False)
                + ":"
                + _canonical_replay_json(value[key])
                for key in sorted(keys, key=_utf16_sort_key)
            )
            + "}"
        )
    raise TypeError(f"tool result contains non-JSON value {type(value).__name__}")


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
    ordered = [require_stored_event(event) for event in events]
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
    state = SessionState(session_id=session_id)
    record_metric(metrics_sink, "kaji.replay.input_events", len(events))
    for event in _legacy_timestamp_order(events):
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
