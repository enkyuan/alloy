from dataclasses import dataclass
from copy import deepcopy
import json
from typing import Any, Dict, List, Optional, Sequence

from kaji.runtime.context import (
    MissingToolIdentityError as MissingToolIdentityError,
    ToolExecutionContext as ToolExecutionContext,
    ToolInvocation as ToolInvocation,
    TurnContext as TurnContext,
)
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.infra.events.replay import SessionState
from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)


@dataclass(frozen=True, slots=True)
class ContextWindow:
    """Bounds provider history by complete conversational turns."""

    max_turns: int | None = 32
    max_characters: int | None = 100_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_turns", self.max_turns),
            ("max_characters", self.max_characters),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or None")


@dataclass(frozen=True, slots=True)
class ContextDiagnostics:
    dropped_turns: int = 0
    dropped_messages: int = 0
    dropped_characters: int = 0


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    messages: List[Dict[str, Any]]
    diagnostics: ContextDiagnostics


class ContextWindowOverflowError(ValueError):
    """The current turn alone cannot fit the configured character cap."""

    def __init__(self, current_turn_characters: int, max_characters: int) -> None:
        super().__init__(
            "Current turn exceeds the context window "
            f"({current_turn_characters} characters, limit {max_characters})"
        )
        self.current_turn_characters = current_turn_characters
        self.max_characters = max_characters


class ContextIntegrityError(ValueError):
    """Provider history contains an orphaned or ambiguous tool result."""


def _message_characters(message: Dict[str, Any]) -> int:
    """Count model-visible history payload using canonical JSON for arguments."""
    content = message.get("content", "")
    count = len(content) if isinstance(content, str) else len(str(content))
    if message.get("role") == "assistant":
        for call in message.get("tool_calls", ()):
            count += len(str(call.get("id", "")))
            count += len(str(call.get("name", "")))
            count += len(
                json.dumps(
                    call.get("arguments", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            )
    elif message.get("role") == "tool":
        count += len(str(message.get("name", "")))
        count += len(str(message.get("tool_call_id", "")))
    return count


def _turn_groups(
    messages: Sequence[Dict[str, Any]],
) -> list[list[Dict[str, Any]]]:
    groups: list[list[Dict[str, Any]]] = []
    pending: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "user":
            if pending:
                raise ContextIntegrityError(
                    "A user message cannot begin while tool calls are pending"
                )
            groups.append([])
        elif not groups:
            groups.append([])
        groups[-1].append(message)

        if role == "assistant":
            for call in message.get("tool_calls", ()):
                call_id = call.get("id")
                if not isinstance(call_id, str) or not call_id:
                    raise ContextIntegrityError(
                        "Assistant tool calls require a non-empty id"
                    )
                if call_id in pending:
                    raise ContextIntegrityError(
                        f"Overlapping assistant tool call id {call_id!r}"
                    )
                pending.add(call_id)
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ContextIntegrityError(
                    "Tool results require a non-empty tool_call_id"
                )
            if call_id not in pending:
                raise ContextIntegrityError(f"Orphan tool result id {call_id!r}")
            pending.remove(call_id)

    if pending:
        raise ContextIntegrityError("Assistant tool calls require matching results")
    return groups


def build_context(
    state: SessionState,
    prompt: SystemPrompt,
    variables: Optional[Dict[str, Any]] = None,
    *,
    window: ContextWindow | None = None,
    metrics_sink: MetricsSink = NOOP_METRICS,
) -> ContextBuildResult:
    """Build provider messages and diagnostics without splitting a turn."""
    resolved = window or ContextWindow()
    groups = _turn_groups(state.messages)
    group_characters = [
        sum(_message_characters(message) for message in group) for group in groups
    ]

    if groups and resolved.max_characters is not None:
        current_characters = group_characters[-1]
        if current_characters > resolved.max_characters:
            raise ContextWindowOverflowError(
                current_turn_characters=current_characters,
                max_characters=resolved.max_characters,
            )

    kept_start = len(groups)
    kept_turns = 0
    kept_characters = 0
    for index in range(len(groups) - 1, -1, -1):
        characters = group_characters[index]
        if resolved.max_turns is not None and kept_turns >= resolved.max_turns:
            break
        if (
            resolved.max_characters is not None
            and kept_characters + characters > resolved.max_characters
        ):
            break
        kept_start = index
        kept_turns += 1
        kept_characters += characters

    dropped = groups[:kept_start]
    kept_messages = [
        deepcopy(message) for group in groups[kept_start:] for message in group
    ]
    diagnostics = ContextDiagnostics(
        dropped_turns=len(dropped),
        dropped_messages=sum(len(group) for group in dropped),
        dropped_characters=sum(group_characters[:kept_start]),
    )
    messages = [
        {"role": "system", "content": prompt.render(variables)},
        *kept_messages,
    ]
    record_metric(metrics_sink, "kaji.context.messages", len(messages))
    record_metric(
        metrics_sink,
        "kaji.context.characters",
        sum(_message_characters(message) for message in messages),
    )
    return ContextBuildResult(messages=messages, diagnostics=diagnostics)


def build_messages(
    state: SessionState,
    prompt: SystemPrompt,
    variables: Optional[Dict[str, Any]] = None,
    *,
    window: ContextWindow | None = None,
    metrics_sink: MetricsSink = NOOP_METRICS,
) -> List[Dict[str, Any]]:
    """Construct provider messages, preserving the historical list API."""
    return build_context(
        state,
        prompt,
        variables,
        window=window,
        metrics_sink=metrics_sink,
    ).messages
