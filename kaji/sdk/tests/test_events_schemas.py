import pytest
import re
from pathlib import Path
from pydantic import TypeAdapter, ValidationError

from kaji.infra.events.replay import replay_session
from kaji.infra.events.schemas import (
    KajiEvent,
    AgentMessageCompleted,
    SessionCreated,
    ToolCallCompleted,
    UserMessage,
)
from kaji.infra.events.types import EventType


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "kaji" / "fixtures" / "events"


def test_event_validation():
    # Valid event
    event = SessionCreated(session_id="test-123")
    assert event.type == EventType.SESSION_CREATED
    assert event.session_id == "test-123"
    assert event.version == "1.0"
    assert event.id is not None
    assert event.timestamp > 0

    # Invalid payload fails loudly
    with pytest.raises(ValidationError):
        # Missing content for UserMessage
        TypeAdapter(UserMessage).validate_python({"session_id": "test-123"})

    with pytest.raises(ValidationError):
        # Extra fields forbidden
        TypeAdapter(SessionCreated).validate_python(
            {"session_id": "test-123", "random_field": "foo"}
        )


def test_event_serialization():
    original = UserMessage(session_id="sess-1", content="Hello world")

    # Serialize to JSON
    json_str = original.model_dump_json()
    assert "user.message" in json_str
    assert "Hello world" in json_str

    # Deserialize back into typed schema
    adapter = TypeAdapter(KajiEvent)
    deserialized = adapter.validate_json(json_str)

    assert isinstance(deserialized, UserMessage)
    assert deserialized.session_id == "sess-1"
    assert deserialized.content == "Hello world"
    assert deserialized.id == original.id


def test_typescript_event_type_values_match_python():
    ts_types = REPO_ROOT / "kaji" / "ts" / "src" / "events" / "types.ts"
    source = ts_types.read_text()
    ts_values = set(re.findall(r': "([^"]+)"', source))
    py_values = {event.value for event in EventType}

    assert ts_values == py_values


@pytest.mark.parametrize(
    "fixture_name,expected_type",
    [
        ("agent-message-completed-with-usage.json", AgentMessageCompleted),
        ("tool-call-completed-with-usage.json", ToolCallCompleted),
    ],
)
def test_shared_usage_event_fixtures_parse_in_python(
    fixture_name: str,
    expected_type: type[object],
):
    payload = (FIXTURES_ROOT / fixture_name).read_text()
    event = TypeAdapter(KajiEvent).validate_json(payload)

    assert isinstance(event, expected_type)
    assert event.tokens is not None
    assert event.tokens.input > 0
    assert event.tokens.output > 0
    assert event.cost_usd is not None
    assert event.cost_usd > 0


@pytest.mark.parametrize(
    "event_type,extra",
    [
        (
            AgentMessageCompleted,
            {"content": "done", "tokens": {"input": -1, "output": 1}},
        ),
        (
            ToolCallCompleted,
            {
                "tool_name": "lookup",
                "tool_call_id": "call_1",
                "result": {"ok": True},
                "tokens": {"input": 1, "output": -1},
            },
        ),
        (AgentMessageCompleted, {"content": "done", "cost_usd": -0.01}),
    ],
)
def test_usage_event_fields_reject_negative_values(
    event_type: type[object],
    extra: dict[str, object],
):
    with pytest.raises(ValidationError):
        TypeAdapter(event_type).validate_python({"session_id": "s1", **extra})


def test_session_replay():
    events: list[KajiEvent] = [
        SessionCreated(session_id="sess-1"),
        UserMessage(session_id="sess-1", content="Hi!"),
        AgentMessageCompleted(session_id="sess-1", content="Hello! How can I help?"),
    ]

    # ensure timestamp order by faking them
    events[0].timestamp = 1.0
    events[1].timestamp = 2.0
    events[2].timestamp = 3.0

    state = replay_session(events)

    assert state.session_id == "sess-1"
    assert state.is_active is True
    assert len(state.messages) == 2

    assert state.messages[0]["role"] == "user"
    assert state.messages[0]["content"] == "Hi!"

    assert state.messages[1]["role"] == "assistant"
    assert state.messages[1]["content"] == "Hello! How can I help?"
