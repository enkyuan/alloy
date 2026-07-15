from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    AgentReasoningStarted,
    KajiEvent,
    StoredKajiEvent,
    ToolApprovalApproved,
    ToolApprovalRejected,
    ToolApprovalRequested,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    TranscriptFinal,
    UserMessage,
    require_stored_event,
)
from kaji.runtime.sessions.replay import apply_event
from kaji.runtime.agents.context import ContextWindow
from kaji.runtime.agents.prompts import SystemPrompt
from kaji.runtime.sessions.context_index import build_context_from_messages
from kaji.runtime.sessions.projector import SessionProjector


class _Metrics:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}

    def record(self, measurement: Any) -> None:
        self.values[measurement.name] = measurement.value


def _stored(event: KajiEvent, sequence: int) -> StoredKajiEvent:
    return require_stored_event(event.model_copy(update={"sequence": sequence}))


def _outcome(call: Callable[[], Any]) -> tuple[str, Any]:
    try:
        result = call()
    except Exception as error:
        return (type(error).__name__, str(error))
    return ("ok", result)


def _valid_history(session_id: str) -> list[KajiEvent]:
    return [
        AgentMessageCompleted(session_id=session_id, content="leading assistant"),
        UserMessage(session_id=session_id, content="hello 😀"),
        AgentMessageCompleted(session_id=session_id, content="ready"),
        TranscriptFinal(session_id=session_id, text="voice input"),
        AgentReasoningStarted(session_id=session_id),
        ToolCallRequested(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-1",
            tool_args={"query": "café"},
        ),
        ToolCallRequested(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-parallel",
            tool_args={"query": "parallel"},
        ),
        ToolApprovalRequested(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-1",
            tool_args={"query": "café"},
            risk="read",
        ),
        ToolApprovalApproved(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-1",
        ),
        ToolCallCompleted(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-parallel",
            result={"answer": "first"},
        ),
        ToolCallCompleted(
            session_id=session_id,
            turn_id="turn-1",
            tool_name="lookup",
            tool_call_id="call-1",
            result={"answer": "🌍"},
        ),
        AgentReasoningStarted(session_id=session_id),
        ToolCallRequested(
            session_id=session_id,
            turn_id="turn-2",
            tool_name="write",
            tool_call_id="call-2",
            tool_args={},
        ),
        ToolApprovalRequested(
            session_id=session_id,
            turn_id="turn-2",
            tool_name="write",
            tool_call_id="call-2",
            tool_args={},
            risk="write",
        ),
        ToolApprovalRejected(
            session_id=session_id,
            turn_id="turn-2",
            tool_name="write",
            tool_call_id="call-2",
            error_code="APPROVAL_REJECTED",
            reason="rejected",
        ),
        ToolCallFailed(
            session_id=session_id,
            turn_id="turn-2",
            tool_name="write",
            tool_call_id="call-2",
            error="rejected",
        ),
        UserMessage(session_id=session_id, content="12345"),
        AgentMessageCompleted(session_id=session_id, content="67890"),
        AgentReasoningStarted(session_id=session_id),
        ToolCallRequested(
            session_id=session_id,
            turn_id="turn-3",
            tool_name="lookup",
            tool_call_id="call-1",
            tool_args={},
        ),
        ToolCallCompleted(
            session_id=session_id,
            turn_id="turn-3",
            tool_name="lookup",
            tool_call_id="call-1",
            result=True,
        ),
    ]


def test_index_matches_full_scan_oracle_for_every_history_prefix() -> None:
    projector = SessionProjector(
        "differential",
        context_window=ContextWindow(max_turns=3, max_characters=80),
    )
    prompt = SystemPrompt("system 😀")
    window = ContextWindow(max_turns=3, max_characters=80)

    for sequence, event in enumerate(_valid_history("differential"), 1):
        projector.apply(_stored(event, sequence))
        oracle = _outcome(
            lambda: build_context_from_messages(
                projector.state,
                prompt,
                window=window,
            )
        )
        indexed = _outcome(
            lambda: projector.build_projected_context(prompt, window=window)
        )
        assert indexed == oracle, f"prefix {sequence} diverged"


@pytest.mark.parametrize(
    "events",
    [
        [
            ToolCallCompleted(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="orphan",
                result={},
            )
        ],
        [
            UserMessage(session_id="malformed", content="start"),
            ToolCallRequested(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="duplicate",
                tool_args={},
            ),
            ToolCallRequested(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="duplicate",
                tool_args={},
            ),
        ],
        [
            UserMessage(session_id="malformed", content="start"),
            ToolCallRequested(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="pending",
                tool_args={},
            ),
            UserMessage(session_id="malformed", content="interrupt"),
        ],
        [
            UserMessage(session_id="malformed", content="start"),
            ToolCallRequested(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="done",
                tool_args={},
            ),
            ToolCallCompleted(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="done",
                result={},
            ),
            ToolCallCompleted(
                session_id="malformed",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="done",
                result={},
            ),
        ],
    ],
)
def test_index_preserves_first_integrity_error_for_every_prefix(
    events: list[KajiEvent],
) -> None:
    projector = SessionProjector("malformed")
    prompt = SystemPrompt("system")

    for sequence, event in enumerate(events, 1):
        projector.apply(_stored(event, sequence))
        oracle = _outcome(lambda: build_context_from_messages(projector.state, prompt))
        indexed = _outcome(lambda: projector.build_projected_context(prompt))
        assert indexed == oracle, f"prefix {sequence} diverged"


def test_indexed_context_is_detached_and_records_bounded_operation_counts() -> None:
    window = ContextWindow(max_turns=32, max_characters=100_000)
    projector = SessionProjector("complexity", context_window=window)
    sequence = 0

    for batch in range(2_000):
        call_id = f"call-{batch}"
        for event in (
            UserMessage(session_id="complexity", content=str(batch)),
            AgentReasoningStarted(session_id="complexity"),
            ToolCallRequested(
                session_id="complexity",
                turn_id=f"turn-{batch}",
                tool_name="lookup",
                tool_call_id=call_id,
                tool_args={"nested": {"batch": batch}},
            ),
            ToolCallCompleted(
                session_id="complexity",
                turn_id=f"turn-{batch}",
                tool_name="lookup",
                tool_call_id=call_id,
                result={"ok": True},
            ),
            AgentMessageCompleted(
                session_id="complexity",
                content=f"done-{batch}",
            ),
        ):
            sequence += 1
            projector.apply(_stored(event, sequence))

    for _ in range(5):
        result = projector.build_projected_context(
            SystemPrompt("system"), window=window
        )

    assistant = next(
        message for message in result.messages if message["role"] == "assistant"
    )
    assistant["tool_calls"][0]["arguments"]["nested"]["batch"] = "changed"
    source = next(
        message
        for message in projector.state.messages[-128:]
        if message["role"] == "assistant" and message.get("tool_calls")
    )
    assert source["tool_calls"][0]["arguments"]["nested"]["batch"] != "changed"

    stats = projector.context_index_stats
    assert stats.full_cold_builds == 1
    assert stats.cold_events == 10_000
    assert stats.incremental_events == 0
    assert stats.suffix_calls == 5
    assert stats.copied_output_messages == (len(result.messages) - 1) * 5
    assert stats.max_visited_turn_entries <= 32
    assert stats.persistent_copied_payload_bytes == 0
    assert stats.turn_entries <= stats.retained_turns
    assert stats.sentinel_entries <= 1
    assert stats.total_entries == stats.turn_entries + stats.sentinel_entries

    sequence += 1
    projector.apply(
        _stored(UserMessage(session_id="complexity", content="latest"), sequence)
    )
    assert projector.latest_user_content() == "latest"
    assert projector.context_index_stats.incremental_events == 1
    assert projector.context_index_stats.latest_user_accesses == 1


def test_wider_window_after_compaction_falls_back_to_full_scan_oracle() -> None:
    configured = ContextWindow(max_turns=2, max_characters=20)
    projector = SessionProjector("fallback", context_window=configured)
    for sequence, event in enumerate(
        [
            UserMessage(session_id="fallback", content="one"),
            AgentMessageCompleted(session_id="fallback", content="1"),
            UserMessage(session_id="fallback", content="two"),
            AgentMessageCompleted(session_id="fallback", content="2"),
            UserMessage(session_id="fallback", content="three"),
        ],
        1,
    ):
        projector.apply(_stored(event, sequence))

    window = ContextWindow(max_turns=None, max_characters=None)
    indexed = projector.build_projected_context(SystemPrompt("system"), window=window)
    oracle = build_context_from_messages(
        projector.state,
        SystemPrompt("system"),
        window=window,
    )
    assert indexed == oracle


def test_indexed_context_records_exact_message_and_character_metrics() -> None:
    metrics = _Metrics()
    projector = SessionProjector("metrics", metrics_sink=metrics)
    events: list[KajiEvent] = [
        UserMessage(session_id="metrics", content="u"),
        AgentMessageCompleted(session_id="metrics", content="a"),
        ToolCallRequested(
            session_id="metrics",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="c",
            tool_args={"emoji": "😀"},
        ),
        ToolCallCompleted(
            session_id="metrics",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="c",
            result="ok",
        ),
    ]
    for sequence, event in enumerate(events, 1):
        projector.apply(_stored(event, sequence))

    projector.build_projected_context(SystemPrompt("😀"))

    assert metrics.values["kaji.context.messages"] == 4
    assert metrics.values["kaji.context.characters"] == 30


def test_index_matches_oracle_at_exact_limit_and_error_precedence() -> None:
    exact = SessionProjector("exact")
    exact.apply(_stored(UserMessage(session_id="exact", content="12345"), 1))
    assert exact.build_projected_context(
        SystemPrompt("system"),
        window=ContextWindow(max_turns=1, max_characters=5),
    ) == build_context_from_messages(
        exact.state,
        SystemPrompt("system"),
        window=ContextWindow(max_turns=1, max_characters=5),
    )

    pending = SessionProjector("pending")
    pending.apply(_stored(UserMessage(session_id="pending", content="12345"), 1))
    pending.apply(
        _stored(
            ToolCallRequested(
                session_id="pending",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="call",
                tool_args={},
            ),
            2,
        )
    )
    window = ContextWindow(max_turns=1, max_characters=1)
    assert (
        _outcome(
            lambda: pending.build_projected_context(
                SystemPrompt("system"), window=window
            )
        )
        == _outcome(
            lambda: build_context_from_messages(
                pending.state,
                SystemPrompt("system"),
                window=window,
            )
        )
        == ("ContextIntegrityError", "Assistant tool calls require matching results")
    )


@pytest.mark.parametrize("mutation", ["append", "remove"])
def test_projector_state_snapshot_cannot_mutate_projection(
    mutation: str,
) -> None:
    projector = SessionProjector("owned")
    projector.apply(_stored(UserMessage(session_id="owned", content="one"), 1))
    snapshot = projector.state
    if mutation == "append":
        snapshot.messages.append({"role": "user", "content": "foreign"})
    else:
        snapshot.messages.pop()

    assert [message["content"] for message in projector.state.messages] == ["one"]
    before_stats = projector.context_index_stats
    projector.apply(_stored(UserMessage(session_id="owned", content="must-apply"), 2))

    assert projector.cursor == 2
    assert projector.applied_events == 2
    assert [message["content"] for message in projector.state.messages] == [
        "one",
        "must-apply",
    ]
    assert projector.context_index_stats.cold_events == before_stats.cold_events + 1


def test_projector_state_snapshot_preserves_replay_cursor_semantics() -> None:
    projector = SessionProjector("snapshot-cursor")
    for sequence, event in enumerate(
        [
            UserMessage(session_id="snapshot-cursor", content="go"),
            AgentReasoningStarted(session_id="snapshot-cursor"),
            ToolCallRequested(
                session_id="snapshot-cursor",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="first",
                tool_args={},
            ),
        ],
        1,
    ):
        projector.apply(_stored(event, sequence))

    snapshot = projector.state
    apply_event(
        snapshot,
        _stored(
            ToolCallRequested(
                session_id="snapshot-cursor",
                turn_id="turn",
                tool_name="lookup",
                tool_call_id="second",
                tool_args={},
            ),
            4,
        ),
    )

    snapshot_assistants = [
        message for message in snapshot.messages if message["role"] == "assistant"
    ]
    assert len(snapshot_assistants) == 1
    assert [call["id"] for call in snapshot_assistants[0]["tool_calls"]] == [
        "first",
        "second",
    ]
    assert len(projector.state.messages[1]["tool_calls"]) == 1


def test_context_index_incremental_rss_is_bounded_in_fresh_processes() -> None:
    worker = Path(__file__).with_name("context_rss_probe.py")

    def measure(mode: str) -> dict[str, int]:
        completed = subprocess.run(
            [sys.executable, str(worker), mode],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return json.loads(completed.stdout)

    baseline = measure("baseline")
    indexed = measure("indexed")
    assert baseline["messages"] == indexed["messages"] == 8_000
    assert max(0, indexed["rss"] - baseline["rss"]) <= 67_108_864


def _ownership_projector() -> SessionProjector:
    projector = SessionProjector("ownership")
    events: list[KajiEvent] = [
        UserMessage(session_id="ownership", content="original"),
        AgentReasoningStarted(session_id="ownership"),
        ToolCallRequested(
            session_id="ownership",
            turn_id="turn",
            tool_name="lookup",
            tool_call_id="call",
            tool_args={"nested": {"value": "original"}},
        ),
        ToolCallCompleted(
            session_id="ownership",
            turn_id="turn",
            tool_name="lookup",
            tool_call_id="call",
            result={"ok": True},
        ),
    ]
    for sequence, event in enumerate(events, 1):
        projector.apply(_stored(event, sequence))
    return projector


def _mutate_projected_payload(messages: list[dict[str, Any]], mutation: str) -> None:
    if mutation == "content":
        messages[0]["content"] = "tampered"
    elif mutation == "element":
        messages[0] = {"role": "user", "content": "tampered"}
    elif mutation == "nested_args":
        messages[1]["tool_calls"][0]["arguments"]["nested"]["value"] = "tampered"
    else:
        messages[1]["tool_calls"].append(
            {"id": "extra", "name": "lookup", "arguments": {}}
        )


@pytest.mark.parametrize(
    ("boundary", "mutation"),
    [
        (boundary, mutation)
        for boundary in ("apply", "suffix", "latest_user")
        for mutation in ("content", "element", "nested_args", "tool_calls")
    ],
)
def test_projector_isolates_in_place_snapshot_mutation_at_every_boundary(
    boundary: str,
    mutation: str,
) -> None:
    projector = _ownership_projector()
    snapshot = projector.state
    before_cursor = projector.cursor
    before_events = projector.applied_events
    before_stats = projector.context_index_stats
    clone = deepcopy(snapshot.messages)
    assert clone == snapshot.messages

    _mutate_projected_payload(snapshot.messages, mutation)
    assert projector.cursor == before_cursor
    assert projector.applied_events == before_events
    assert projector.context_index_stats == before_stats
    assert projector.state.messages == clone

    if boundary == "apply":
        projector.apply(_stored(AgentReasoningStarted(session_id="ownership"), 5))
        assert projector.cursor == before_cursor + 1
        assert projector.applied_events == before_events + 1
        assert projector.context_index_stats.cold_events == before_stats.cold_events + 1
    elif boundary == "suffix":
        result = projector.build_projected_context(SystemPrompt("system"))
        assert result.messages[1:] == clone
        assert (
            projector.context_index_stats.suffix_calls == before_stats.suffix_calls + 1
        )
    else:
        assert projector.latest_user_content() == "original"
        assert (
            projector.context_index_stats.latest_user_accesses
            == before_stats.latest_user_accesses + 1
        )

    assert projector.state.messages == clone


def test_repeated_tool_requests_scan_each_new_call_once() -> None:
    projector = SessionProjector(
        "linear-calls",
        context_window=ContextWindow(max_turns=None, max_characters=None),
    )
    projector.apply(_stored(UserMessage(session_id="linear-calls", content="go"), 1))
    projector.apply(_stored(AgentReasoningStarted(session_id="linear-calls"), 2))
    expected_argument_bytes = 0
    for index in range(100):
        arguments = {"index": index}
        expected_argument_bytes += len(
            json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        projector.apply(
            _stored(
                ToolCallRequested(
                    session_id="linear-calls",
                    turn_id="turn",
                    tool_name="lookup",
                    tool_call_id=f"call-{index}",
                    tool_args=arguments,
                ),
                index + 3,
            )
        )

    stats = projector.context_index_stats
    assert stats.scanned_tool_calls == 100
    assert stats.scanned_tool_argument_bytes == expected_argument_bytes


def test_context_windows_are_validated_and_defensively_snapshotted() -> None:
    configured = ContextWindow(max_turns=2, max_characters=None)
    projector = SessionProjector("windows", context_window=configured)
    object.__setattr__(configured, "max_turns", 1)
    for sequence, event in enumerate(
        [
            UserMessage(session_id="windows", content="one"),
            AgentMessageCompleted(session_id="windows", content="1"),
            UserMessage(session_id="windows", content="two"),
            AgentMessageCompleted(session_id="windows", content="2"),
            UserMessage(session_id="windows", content="three"),
        ],
        1,
    ):
        projector.apply(_stored(event, sequence))
    assert [
        message["content"]
        for message in projector.build_projected_context(
            SystemPrompt("system")
        ).messages[1:]
    ] == ["two", "2", "three"]

    invalid = ContextWindow()
    object.__setattr__(invalid, "max_turns", 0)
    indexed = _outcome(
        lambda: projector.build_projected_context(
            SystemPrompt("system"), window=invalid
        )
    )
    oracle = _outcome(
        lambda: build_context_from_messages(
            projector.state,
            SystemPrompt("system"),
            window=invalid,
        )
    )
    assert (
        indexed
        == oracle
        == (
            "ValueError",
            "max_turns must be a positive integer or None",
        )
    )
