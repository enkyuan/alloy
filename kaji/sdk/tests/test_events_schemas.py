import json
import re
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from kaji.infra.events.replay import replay_session
from kaji.infra.events.schemas import (
    AgentTurnFailed,
    KajiEvent,
    AgentMessageCompleted,
    SessionCreated,
    StoredKajiEvent,
    ToolCallCompleted,
    UserMessage,
    require_stored_event,
)
from kaji.infra.events.types import EventType


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "kaji" / "fixtures" / "events"
CONFORMANCE_FIXTURE = REPO_ROOT / "kaji" / "contracts" / "events" / "conformance.json"


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
    original = UserMessage(
        session_id="sess-1",
        turn_id="turn-1",
        content="Hello world",
    )

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
    assert deserialized.turn_id == "turn-1"
    assert deserialized.sequence is None
    assert '"sequence"' not in json_str


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
    drafts: list[KajiEvent] = [
        SessionCreated(session_id="sess-1", sequence=1),
        UserMessage(session_id="sess-1", content="Hi!", sequence=2),
        AgentMessageCompleted(
            session_id="sess-1",
            content="Hello! How can I help?",
            sequence=3,
        ),
    ]
    events: list[StoredKajiEvent] = [require_stored_event(event) for event in drafts]
    state = replay_session(events)

    assert state.session_id == "sess-1"
    assert state.is_active is True
    assert len(state.messages) == 2

    assert state.messages[0]["role"] == "user"
    assert state.messages[0]["content"] == "Hi!"

    assert state.messages[1]["role"] == "assistant"
    assert state.messages[1]["content"] == "Hello! How can I help?"


def test_shared_session_event_conformance_fixture_replays_in_python() -> None:
    fixture = json.loads(CONFORMANCE_FIXTURE.read_text())
    session_payload = fixture["events"][0]
    parsed = TypeAdapter(KajiEvent).validate_python(session_payload)
    assert isinstance(parsed, SessionCreated)

    stored = require_stored_event(parsed)
    state = replay_session([stored])

    assert stored.version == "1.0"
    assert isinstance(stored.timestamp, float)
    assert stored.sequence == 1
    assert state.session_id == "session-1"
    assert state.is_active is True


def test_shared_turn_failure_conformance_fixture_is_bounded_and_turn_scoped() -> None:
    fixture = json.loads(CONFORMANCE_FIXTURE.read_text())
    parsed = TypeAdapter(KajiEvent).validate_python(fixture["events"][2])

    assert isinstance(parsed, AgentTurnFailed)
    assert parsed.turn_id == "turn-1"
    assert parsed.error == "Agent turn failed"

    with pytest.raises(ValidationError):
        TypeAdapter(AgentTurnFailed).validate_python(
            {"session_id": "session-1", "error": "Agent turn failed"}
        )
    with pytest.raises(ValidationError):
        AgentTurnFailed(session_id="session-1", turn_id="turn-1", error="x" * 201)
