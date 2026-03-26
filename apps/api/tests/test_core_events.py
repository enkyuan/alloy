import pytest

from app.core.events import (
    AgentResponse,
    build_event_envelope,
    is_supported_event_version,
    parse_event_envelope,
)


def test_core_events_build_and_parse_event_envelope_with_model_payload():
    envelope = build_event_envelope(
        event_type="agent.response",
        user_id="user_123",
        payload=AgentResponse(content="hello"),
        metadata={"source": "unit-test"},
    )

    assert envelope["version"] == "1.0"
    assert envelope["type"] == "agent.response"
    assert envelope["user_id"] == "user_123"
    assert isinstance(envelope["payload"], dict)
    assert envelope["payload"]["content"] == "hello"

    parsed = parse_event_envelope(envelope)
    assert parsed.type == "agent.response"
    assert parsed.user_id == "user_123"
    assert parsed.metadata["source"] == "unit-test"


def test_core_events_parse_event_envelope_accepts_legacy_message_without_version():
    legacy = {
        "type": "agent.response",
        "user_id": "legacy_user",
        "payload": AgentResponse(content="legacy").model_dump(mode="json"),
    }

    parsed = parse_event_envelope(legacy)
    assert parsed.version == "1.0"
    assert parsed.type == "agent.response"


def test_core_events_supported_event_version_uses_major_semver_compatibility():
    assert is_supported_event_version("1.0")
    assert is_supported_event_version("1.7")
    assert not is_supported_event_version("2.0")


def test_core_events_parse_event_envelope_rejects_unsupported_major_version():
    envelope = {
        "version": "2.0",
        "type": "agent.response",
        "user_id": "user_123",
        "payload": AgentResponse(content="hello").model_dump(mode="json"),
    }

    with pytest.raises(ValueError, match="Unsupported event envelope version"):
        parse_event_envelope(envelope)


def test_core_events_parse_event_envelope_rejects_string_payload_contract_drift():
    envelope = {
        "version": "1.0",
        "type": "agent.response",
        "user_id": "user_123",
        "payload": AgentResponse(content="hello").model_dump_json(),
    }

    with pytest.raises(ValueError, match="String event payloads are no longer supported"):
        parse_event_envelope(envelope)
