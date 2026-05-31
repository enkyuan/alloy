import pytest
from pydantic import TypeAdapter, ValidationError

from agentkit.infra.events.replay import ReplaySession
from agentkit.infra.events.schemas import (
    AgentKitEvent,
    AgentMessageCompleted,
    SessionCreated,
    UserMessage,
)
from agentkit.infra.events.types import EventType


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
    adapter = TypeAdapter(AgentKitEvent)
    deserialized = adapter.validate_json(json_str)

    assert isinstance(deserialized, UserMessage)
    assert deserialized.session_id == "sess-1"
    assert deserialized.content == "Hello world"
    assert deserialized.id == original.id


def test_session_replay():
    events: list[AgentKitEvent] = [
        SessionCreated(session_id="sess-1"),
        UserMessage(session_id="sess-1", content="Hi!"),
        AgentMessageCompleted(session_id="sess-1", content="Hello! How can I help?"),
    ]

    # ensure timestamp order by faking them
    events[0].timestamp = 1.0
    events[1].timestamp = 2.0
    events[2].timestamp = 3.0

    state = ReplaySession(events)

    assert state.session_id == "sess-1"
    assert state.is_active is True
    assert len(state.messages) == 2

    assert state.messages[0]["role"] == "user"
    assert state.messages[0]["content"] == "Hi!"

    assert state.messages[1]["role"] == "assistant"
    assert state.messages[1]["content"] == "Hello! How can I help?"
