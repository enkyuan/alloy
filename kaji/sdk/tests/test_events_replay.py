import pytest

from kaji.infra.events.replay import (
    LegacyEventOrderingWarning,
    replay_legacy_session,
    replay_session,
)
from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    KajiEvent,
    SessionClosed,
    SessionCreated,
    StoredKajiEvent,
    ToolCallCompleted,
    ToolCallFailed,
    TranscriptFinal,
    UserMessage,
    require_stored_event,
)


def _stored(*events: KajiEvent) -> list[StoredKajiEvent]:
    return [require_stored_event(event) for event in events]


def test_replay_session_builds_message_history_from_sequences() -> None:
    events = [
        SessionCreated(session_id="s1", timestamp=6.0, sequence=1),
        UserMessage(session_id="s1", content="hi", timestamp=5.0, sequence=2),
        AgentMessageCompleted(
            session_id="s1", content="hello", timestamp=4.0, sequence=3
        ),
        TranscriptFinal(session_id="s1", text="voice turn", timestamp=3.0, sequence=4),
        ToolCallCompleted(
            session_id="s1",
            tool_name="search",
            tool_call_id="c1",
            result={"ok": True},
            timestamp=2.0,
            sequence=5,
        ),
        SessionClosed(session_id="s1", timestamp=1.0, sequence=6),
    ]
    state = replay_session(_stored(*events))
    assert state.session_id == "s1"
    assert state.is_active is False
    assert [message["role"] for message in state.messages] == [
        "user",
        "assistant",
        "user",
        "tool",
    ]


def test_replay_session_projects_failed_tool_call() -> None:
    events = [
        UserMessage(session_id="s1", content="do it", sequence=1),
        ToolCallFailed(
            session_id="s1",
            tool_name="search",
            tool_call_id="c1",
            error="boom",
            sequence=2,
        ),
    ]
    state = replay_session(_stored(*events))
    tool_messages = [message for message in state.messages if message["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["name"] == "search"
    assert "boom" in tool_messages[0]["content"]


def test_replay_session_empty_log_raises() -> None:
    with pytest.raises(ValueError, match="empty event log"):
        replay_session([])


def test_fully_legacy_replay_uses_stable_timestamp_and_input_index_order() -> None:
    events = [
        UserMessage(session_id="s1", content="same-first", timestamp=2.0),
        UserMessage(session_id="s1", content="earlier", timestamp=1.0),
        UserMessage(session_id="s1", content="same-second", timestamp=2.0),
    ]
    with pytest.warns(LegacyEventOrderingWarning):
        state = replay_legacy_session(events)
    assert [message["content"] for message in state.messages] == [
        "earlier",
        "same-first",
        "same-second",
    ]


@pytest.mark.parametrize(
    ("events", "message"),
    [
        (
            [
                UserMessage(session_id="s1", content="one", sequence=1),
                UserMessage(session_id="s2", content="two", sequence=2),
            ],
            "mixed sessions",
        ),
        (
            [
                UserMessage(session_id="s1", content="one", sequence=1),
                UserMessage(session_id="s1", content="two"),
            ],
            "mixed sequenced and unsequenced",
        ),
        (
            [
                UserMessage(session_id="s1", content="one", sequence=1),
                UserMessage(session_id="s1", content="two", sequence=1),
            ],
            "duplicate event sequences",
        ),
        (
            [
                UserMessage(session_id="s1", content="two", sequence=2),
                UserMessage(session_id="s1", content="one", sequence=1),
            ],
            "non-monotonic event sequences",
        ),
    ],
)
def test_replay_rejects_ambiguous_or_invalid_logs(
    events: list[UserMessage], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replay_session(events)  # ty: ignore[invalid-argument-type]


def test_stable_replay_rejects_a_fully_unsequenced_legacy_log() -> None:
    events = [UserMessage(session_id="s1", content="legacy")]
    with pytest.raises(ValueError, match="positive sequence"):
        replay_session(events)  # ty: ignore[invalid-argument-type]


def test_legacy_replay_rejects_sequenced_events() -> None:
    events = [UserMessage(session_id="s1", content="stored", sequence=1)]
    with pytest.raises(ValueError, match="only fully unsequenced"):
        replay_legacy_session(events)
