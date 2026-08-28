"""Projection-owned provider-context index.

The index stores only message ranges, counts, and pending call identifiers.
Projected message payloads remain owned by ``SessionState.messages``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any, Dict, Optional

from kaji.infra.observability.protocols import (
    MetricsSink,
    NOOP_METRICS,
    record_metric,
)
from kaji.runtime.agents.context import (
    ContextBuildResult,
    ContextDiagnostics,
    ContextIntegrityError,
    ContextWindow,
    ContextWindowOverflowError,
    _message_characters,
    build_context,
)
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.sessions.replay import SessionState


@dataclass(slots=True)
class ContextTurn:
    message_start: int
    message_end: int
    characters: int
    pending_tool_call_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class ContextIndexStats:
    full_cold_builds: int
    cold_events: int
    incremental_events: int
    suffix_calls: int
    max_visited_turn_entries: int
    copied_output_messages: int
    persistent_copied_payload_bytes: int
    retained_turns: int
    turn_entries: int
    sentinel_entries: int
    total_entries: int
    latest_user_accesses: int
    scanned_tool_calls: int
    scanned_tool_argument_bytes: int


class ContextProjectionMutationError(RuntimeError):
    """Projected messages were mutated outside ``SessionProjector``."""


def build_context_from_messages(
    state: SessionState,
    prompt: SystemPrompt,
    variables: Optional[Dict[str, Any]] = None,
    *,
    window: ContextWindow | None = None,
    metrics_sink: MetricsSink = NOOP_METRICS,
) -> ContextBuildResult:
    """Full-scan compatibility oracle for arbitrary detached message arrays."""
    resolved = _snapshot_window(window)
    return build_context(
        state,
        prompt,
        variables,
        window=resolved,
        metrics_sink=metrics_sink,
    )


def _snapshot_window(window: ContextWindow | None) -> ContextWindow:
    """Validate and detach caller-owned context limits."""
    resolved = ContextWindow() if window is None else window
    return ContextWindow(
        max_turns=resolved.max_turns,
        max_characters=resolved.max_characters,
    )


def _tool_call_measurement(call: Dict[str, Any]) -> tuple[int, int]:
    arguments = json.dumps(
        call.get("arguments", {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    characters = (
        len(str(call.get("id", ""))) + len(str(call.get("name", ""))) + len(arguments)
    )
    return characters, len(arguments.encode("utf-8"))


class ContextIndex:
    """Maintain the bounded turn suffix while projection advances once."""

    def __init__(
        self,
        state: SessionState,
        retention_window: ContextWindow | None = None,
    ) -> None:
        self._state = state
        self._messages = state.messages
        self._retention_window = _snapshot_window(retention_window)
        self._turns: list[ContextTurn] = []
        self._retained_characters = 0
        self._prefix_turns = 0
        self._prefix_messages = 0
        self._prefix_characters = 0
        self._latest_user_index: int | None = None
        self._integrity_error: str | None = None
        self._mutable_message_index: int | None = None
        self._projected_message_count = 0

        self._cold_open = True
        self._full_cold_builds = 1
        self._cold_events = 0
        self._incremental_events = 0
        self._suffix_calls = 0
        self._max_visited_turn_entries = 0
        self._copied_output_messages = 0
        self._latest_user_accesses = 0
        self._scanned_tool_calls = 0
        self._scanned_tool_argument_bytes = 0

    @property
    def stats(self) -> ContextIndexStats:
        turn_entries = len(self._turns)
        sentinel_entries = int(self._prefix_turns > 0)
        return ContextIndexStats(
            full_cold_builds=self._full_cold_builds,
            cold_events=self._cold_events,
            incremental_events=self._incremental_events,
            suffix_calls=self._suffix_calls,
            max_visited_turn_entries=self._max_visited_turn_entries,
            copied_output_messages=self._copied_output_messages,
            persistent_copied_payload_bytes=0,
            retained_turns=len(self._turns),
            turn_entries=turn_entries,
            sentinel_entries=sentinel_entries,
            total_entries=turn_entries + sentinel_entries,
            latest_user_accesses=self._latest_user_accesses,
            scanned_tool_calls=self._scanned_tool_calls,
            scanned_tool_argument_bytes=self._scanned_tool_argument_bytes,
        )

    def seal_cold_build(self) -> None:
        self._cold_open = False

    def assert_projection_owned(self) -> None:
        if (
            self._state.messages is not self._messages
            or len(self._messages) != self._projected_message_count
        ):
            raise ContextProjectionMutationError(
                "SessionState.messages changed outside SessionProjector"
            )

    def apply(self, message_index: int | None) -> None:
        if self._cold_open:
            self._cold_events += 1
        else:
            self._incremental_events += 1
        if message_index is None:
            return

        message = self._messages[message_index]
        role = message.get("role")
        appended = message_index >= self._projected_message_count
        self._projected_message_count = len(self._messages)
        if not appended:
            self._update_assistant(message_index, message)
            self._compact()
            return

        if role == "user":
            if self._pending_ids():
                self._fault("A user message cannot begin while tool calls are pending")
            self._latest_user_index = message_index
            self._append_turn(message_index, message)
        else:
            turn = self._current_turn(message_index)
            characters = (
                self._assistant_characters(message)
                if role == "assistant"
                else _message_characters(message)
            )
            turn.message_end = message_index + 1
            turn.characters += characters
            self._retained_characters += characters
            if role == "assistant":
                self._mutable_message_index = message_index
                for call in message.get("tool_calls", ()):
                    self._request_tool_call(turn, call.get("id"))
            elif role == "tool":
                self._resolve_tool_call(turn, message.get("tool_call_id"))
        self._compact()

    def suffix(
        self,
        prompt: SystemPrompt,
        variables: Optional[Dict[str, Any]] = None,
        *,
        window: ContextWindow | None = None,
        metrics_sink: MetricsSink = NOOP_METRICS,
    ) -> ContextBuildResult:
        resolved = _snapshot_window(
            self._retention_window if window is None else window
        )
        self.assert_projection_owned()
        self.seal_cold_build()
        self._suffix_calls += 1

        if self._integrity_error is not None:
            raise ContextIntegrityError(self._integrity_error)
        if self._pending_ids():
            raise ContextIntegrityError("Assistant tool calls require matching results")
        if self._prefix_turns and self._is_wider_than_retention(resolved):
            return build_context_from_messages(
                self._state,
                prompt,
                variables,
                window=resolved,
                metrics_sink=metrics_sink,
            )

        if self._turns and resolved.max_characters is not None:
            current_characters = self._turns[-1].characters
            if current_characters > resolved.max_characters:
                raise ContextWindowOverflowError(
                    current_turn_characters=current_characters,
                    max_characters=resolved.max_characters,
                )

        kept_start = len(self._turns)
        kept_turns = 0
        kept_characters = 0
        visited = 0
        for index in range(len(self._turns) - 1, -1, -1):
            visited += 1
            turn = self._turns[index]
            if resolved.max_turns is not None and kept_turns >= resolved.max_turns:
                break
            if (
                resolved.max_characters is not None
                and kept_characters + turn.characters > resolved.max_characters
            ):
                break
            kept_start = index
            kept_turns += 1
            kept_characters += turn.characters
        self._max_visited_turn_entries = max(
            self._max_visited_turn_entries,
            visited,
        )

        dropped_turns = self._prefix_turns + kept_start
        dropped_messages = self._prefix_messages + sum(
            turn.message_end - turn.message_start for turn in self._turns[:kept_start]
        )
        dropped_characters = self._prefix_characters + sum(
            turn.characters for turn in self._turns[:kept_start]
        )
        kept_messages: list[Dict[str, Any]] = []
        if kept_start < len(self._turns):
            start = self._turns[kept_start].message_start
            end = self._turns[-1].message_end
            kept_messages = deepcopy(self._messages[start:end])
        self._copied_output_messages += len(kept_messages)

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
        return ContextBuildResult(
            messages=messages,
            diagnostics=ContextDiagnostics(
                dropped_turns=dropped_turns,
                dropped_messages=dropped_messages,
                dropped_characters=dropped_characters,
            ),
        )

    def latest_user_content(self) -> str | None:
        self.assert_projection_owned()
        self._latest_user_accesses += 1
        if self._latest_user_index is None:
            return None
        content = self._messages[self._latest_user_index].get("content")
        return content if isinstance(content, str) else None

    def _append_turn(self, message_index: int, message: Dict[str, Any]) -> None:
        characters = _message_characters(message)
        self._turns.append(
            ContextTurn(
                message_start=message_index,
                message_end=message_index + 1,
                characters=characters,
            )
        )
        self._retained_characters += characters
        self._mutable_message_index = None

    def _current_turn(self, message_index: int) -> ContextTurn:
        if not self._turns:
            self._turns.append(
                ContextTurn(
                    message_start=message_index,
                    message_end=message_index,
                    characters=0,
                )
            )
        return self._turns[-1]

    def _update_assistant(
        self,
        message_index: int,
        message: Dict[str, Any],
    ) -> None:
        turn = self._current_turn(message_index)
        if self._mutable_message_index != message_index:
            self._fault(
                "Projected context update does not target the current assistant"
            )
            return
        calls = message.get("tool_calls", ())
        if not calls:
            self._fault("Projected assistant update requires a tool call")
            return
        call = calls[-1]
        characters = self._scan_tool_call(call)
        turn.characters += characters
        self._retained_characters += characters
        call_id = call.get("id")
        self._request_tool_call(turn, call_id)

    def _assistant_characters(self, message: Dict[str, Any]) -> int:
        characters = _message_characters(
            {"role": "assistant", "content": message.get("content", "")}
        )
        for call in message.get("tool_calls", ()):
            characters += self._scan_tool_call(call)
        return characters

    def _scan_tool_call(self, call: Dict[str, Any]) -> int:
        characters, argument_bytes = _tool_call_measurement(call)
        self._scanned_tool_calls += 1
        self._scanned_tool_argument_bytes += argument_bytes
        return characters

    def _request_tool_call(self, turn: ContextTurn, call_id: object) -> None:
        if not isinstance(call_id, str) or not call_id:
            self._fault("Assistant tool calls require a non-empty id")
            return
        if call_id in turn.pending_tool_call_ids:
            self._fault(f"Overlapping assistant tool call id {call_id!r}")
            return
        turn.pending_tool_call_ids.add(call_id)

    def _resolve_tool_call(self, turn: ContextTurn, call_id: str | None) -> None:
        if not call_id:
            self._fault("Tool results require a non-empty tool_call_id")
            return
        if call_id not in turn.pending_tool_call_ids:
            self._fault(f"Orphan tool result id {call_id!r}")
            return
        turn.pending_tool_call_ids.remove(call_id)

    def _pending_ids(self) -> set[str]:
        return self._turns[-1].pending_tool_call_ids if self._turns else set()

    def _fault(self, message: str) -> None:
        if self._integrity_error is None:
            self._integrity_error = message

    def _compact(self) -> None:
        while len(self._turns) > 1:
            exceeds_turns = (
                self._retention_window.max_turns is not None
                and len(self._turns) > self._retention_window.max_turns
            )
            exceeds_characters = (
                self._retention_window.max_characters is not None
                and self._retained_characters > self._retention_window.max_characters
            )
            if not exceeds_turns and not exceeds_characters:
                return
            dropped = self._turns.pop(0)
            self._retained_characters -= dropped.characters
            self._prefix_turns += 1
            self._prefix_messages += dropped.message_end - dropped.message_start
            self._prefix_characters += dropped.characters

    def _is_wider_than_retention(self, window: ContextWindow) -> bool:
        return self._is_wider(
            window.max_turns, self._retention_window.max_turns
        ) or self._is_wider(
            window.max_characters,
            self._retention_window.max_characters,
        )

    @staticmethod
    def _is_wider(requested: int | None, retained: int | None) -> bool:
        if retained is None:
            return False
        return requested is None or requested > retained
