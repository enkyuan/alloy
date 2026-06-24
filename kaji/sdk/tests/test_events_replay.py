import pytest

from kaji.infra.events.replay import replay_session
from kaji.infra.events.schemas import (
    AgentMessageCompleted,
    SessionClosed,
    SessionCreated,
    ToolCallCompleted,
    ToolCallFailed,
    TranscriptFinal,
    UserMessage,
)


def test_replay_session_builds_message_history():
    events = [
        SessionCreated(session_id="s1", timestamp=1.0),
        UserMessage(session_id="s1", content="hi", timestamp=2.0),
        AgentMessageCompleted(session_id="s1", content="hello", timestamp=3.0),
        TranscriptFinal(session_id="s1", text="voice turn", timestamp=4.0),
        ToolCallCompleted(
            session_id="s1",
            tool_name="search",
            tool_call_id="c1",
            result={"ok": True},
            timestamp=5.0,
        ),
        SessionClosed(session_id="s1", timestamp=6.0),
    ]
    state = replay_session(events)
    assert state.session_id == "s1"
    assert state.is_active is False
    assert len(state.messages) == 4
    assert state.messages[0]["role"] == "user"
    assert state.messages[1]["role"] == "assistant"
    assert state.messages[2]["content"] == "voice turn"
    assert state.messages[3]["role"] == "tool"


def test_replay_session_projects_failed_tool_call():
    events = [
        UserMessage(session_id="s1", content="do it", timestamp=1.0),
        ToolCallFailed(
            session_id="s1",
            tool_name="search",
            tool_call_id="c1",
            error="boom",
            timestamp=2.0,
        ),
    ]
    state = replay_session(events)
    # The failure is recorded as a tool message carrying the error, so the loop
    # sees it instead of re-requesting the same tool.
    tool_messages = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["name"] == "search"
    assert "boom" in tool_messages[0]["content"]


def test_replay_session_empty_log_raises():
    with pytest.raises(ValueError, match="empty event log"):
        replay_session([])


def test_replay_session_sorts_out_of_order_timestamps():
    events = [
        UserMessage(session_id="s1", content="second", timestamp=2.0),
        UserMessage(session_id="s1", content="first", timestamp=1.0),
    ]
    state = replay_session(events)
    assert state.messages[0]["content"] == "first"
    assert state.messages[1]["content"] == "second"
