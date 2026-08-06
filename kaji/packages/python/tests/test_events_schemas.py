import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from kaji.infra.events import schemas as event_schemas
from kaji.runtime.sessions.replay import replay_session
from kaji.infra.events.schemas import (
    AgentTurnExhausted,
    AgentTurnFailed,
    KajiEvent,
    AgentMessageCompleted,
    MemoryRetrievalCompleted,
    SessionCreated,
    StoredKajiEvent,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
    ToolApprovalRejected,
    UserMessage,
    WorkflowCompleted,
    event_defaults,
    revalidate_new_event,
    require_stored_event,
    validate_new_event_python,
    validate_stored_event_python,
)
from kaji.infra.events import errors as event_errors
from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.types import EventType
from kaji.core.determinism import SYSTEM_CLOCK


REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_ROOT = REPO_ROOT / "kaji" / "fixtures" / "events"
CONFORMANCE_FIXTURE = REPO_ROOT / "kaji" / "contracts" / "events" / "conformance.json"
INVALID_CONFORMANCE_FIXTURE = (
    REPO_ROOT / "kaji" / "contracts" / "events" / "conformance-invalid.json"
)
NEW_EVENT_SCHEMA = (
    REPO_ROOT / "kaji" / "contracts" / "events" / "new-kaji-event-v1.schema.json"
)
STORED_EVENT_SCHEMA = (
    REPO_ROOT / "kaji" / "contracts" / "events" / "stored-kaji-event-v1.schema.json"
)


class _FixedIds:
    def __init__(self, value: str) -> None:
        self.value = value

    def next(self, scope: object) -> str:
        del scope
        return self.value


def _event_with_durable_subject(subject: str, value: object):
    base: dict[str, Any] = {
        "id": f"event-{subject}",
        "session_id": "session",
        "timestamp": 1.0,
    }
    if subject == "tool_result":
        event = ToolCallCompleted(
            **base,
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            result={},
        )
        cast(Any, event).result = value
        return event
    if subject == "workflow_result":
        event = WorkflowCompleted(**base, workflow_name="workflow", result={})
        cast(Any, event).result = value
        return event
    if subject == "event_metadata":
        event = UserMessage(**base, content="hello")
        cast(Any, event).metadata = {"value": value}
        return event
    if subject == "memory_document":
        event = MemoryRetrievalCompleted(
            **base,
            query="query",
            documents=[{}],
        )
        cast(Any, event.documents[0])["value"] = value
        return event
    if subject == "pending_tool_call":
        event = AgentTurnExhausted(
            **base,
            max_iterations=1,
            pending_tool_calls=[{}],
        )
        cast(Any, event.pending_tool_calls[0])["value"] = value
        return event
    if subject == "event":
        event = UserMessage(**base, content="hello")
        cast(Any, event).content = value
        return event
    raise AssertionError(f"unhandled subject {subject}")


@pytest.mark.parametrize(
    "subject",
    [
        "tool_result",
        "workflow_result",
        "event_metadata",
        "memory_document",
        "pending_tool_call",
        "event",
    ],
)
def test_in_process_durable_subjects_retain_typed_invalid_classification(
    subject: str,
) -> None:
    event = _event_with_durable_subject(subject, object())
    error_type = getattr(event_errors, "InvalidDurableValueError")

    with pytest.raises(error_type) as captured:
        revalidate_new_event(event)

    assert captured.value.code == "INVALID_DURABLE_VALUE"
    assert captured.value.subject == subject


@pytest.mark.parametrize(
    ("subject", "limit"),
    [
        ("tool_result", 65_536),
        ("workflow_result", 1_048_576),
        ("event_metadata", 1_048_576),
        ("memory_document", 1_048_576),
        ("pending_tool_call", 1_048_576),
        ("event", 1_048_576),
    ],
)
def test_in_process_durable_subjects_retain_typed_limit_classification(
    subject: str,
    limit: int,
) -> None:
    event = _event_with_durable_subject(subject, "😀" * (limit // 4 + 1))
    error_type = getattr(event_errors, "DurableJsonLimitError")

    with pytest.raises(error_type) as captured:
        revalidate_new_event(event)

    assert captured.value.code == "EVENT_PAYLOAD_TOO_LARGE"
    assert captured.value.subject == subject
    assert captured.value.max_bytes == limit


def test_raw_wire_durable_failure_remains_event_schema_incompatible() -> None:
    document: dict[str, Any] = {
        "id": "event",
        "version": "1.0",
        "timestamp": 1.0,
        "type": EventType.TOOL_CALL_COMPLETED,
        "session_id": "session",
        "turn_id": "turn",
        "tool_name": "tool",
        "tool_call_id": "call",
        "result": object(),
        "metadata": {},
    }

    with pytest.raises(EventSchemaIncompatibleError) as captured:
        validate_new_event_python(document)

    assert captured.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert captured.value.path == "/result"


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


def test_wire_validation_runs_before_constructor_defaults() -> None:
    constructed = SessionCreated(session_id="s")
    assert constructed.id
    assert constructed.version == "1.0"
    assert constructed.timestamp > 0

    with pytest.raises(EventSchemaIncompatibleError) as raised:
        validate_new_event_python({"type": "session.created", "session_id": "s"})
    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == "/id"


@pytest.mark.parametrize(
    ("stored", "schema_path", "validator"),
    [
        (False, NEW_EVENT_SCHEMA, validate_new_event_python),
        (True, STORED_EVENT_SCHEMA, validate_stored_event_python),
    ],
)
def test_wire_validation_uses_the_discriminated_variant(
    monkeypatch: pytest.MonkeyPatch,
    stored: bool,
    schema_path: Path,
    validator: object,
) -> None:
    payload = json.loads(CONFORMANCE_FIXTURE.read_text())["events"][1]
    document = dict(payload)
    if not stored:
        document.pop("sequence")

    selected: list[tuple[bool, str]] = []
    select_variant = event_schemas._variant_validator

    def track_variant(stored: bool, event_type: str) -> Any:
        selected.append((stored, event_type))
        return select_variant(stored, event_type)

    monkeypatch.setattr(event_schemas, "_variant_validator", track_variant)
    assert Draft202012Validator(
        json.loads(schema_path.read_text()),
        format_checker=FormatChecker(),
    ).is_valid(document)
    assert cast(Any, validator)(document).type.value == document["type"]
    assert selected == [(stored, document["type"])]


def test_injected_event_id_defaults_are_validated() -> None:
    with event_defaults(_FixedIds("custom-event-id"), SYSTEM_CLOCK):
        event = SessionCreated(session_id="s")
    assert event.id == "custom-event-id"
    assert event.version == "1.0"
    assert event.timestamp > 0

    with event_defaults(_FixedIds(""), SYSTEM_CLOCK):
        with pytest.raises(ValidationError):
            SessionCreated(session_id="s")


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("agent.message.completed", {"content": "done"}),
        (
            "tool.call.completed",
            {
                "turn_id": "turn",
                "tool_name": "tool",
                "tool_call_id": "call",
                "result": {"ok": True},
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "usage",
    [
        {"tokens": {"input": 1, "output": 2}, "cost_usd": 0.25},
        {"tokens": None, "cost_usd": None},
        {},
    ],
    ids=["populated", "null", "omitted"],
)
def test_usage_fields_match_canonical_and_runtime_wire_validation(
    event_type: str,
    payload: dict[str, object],
    usage: dict[str, object],
) -> None:
    base = {
        "id": "event",
        "version": "1.0",
        "timestamp": 0,
        "type": event_type,
        "session_id": "session",
        **payload,
        **usage,
    }
    for stored, schema_path, runtime_validator in (
        (False, NEW_EVENT_SCHEMA, validate_new_event_python),
        (True, STORED_EVENT_SCHEMA, validate_stored_event_python),
    ):
        document = {**base, **({"sequence": 1} if stored else {})}
        schema = json.loads(schema_path.read_text())
        canonical = Draft202012Validator(schema, format_checker=FormatChecker())
        assert canonical.is_valid(document)
        assert runtime_validator(document).type.value == event_type


@pytest.mark.parametrize(
    ("event_type", "payload", "bounded_field"),
    [
        ("agent.turn.failed", {"turn_id": "turn"}, "error"),
        (
            "tool.call.failed",
            {"turn_id": "turn", "tool_name": "tool", "tool_call_id": "call"},
            "error",
        ),
        (
            "tool.approval.rejected",
            {
                "turn_id": "turn",
                "tool_name": "tool",
                "tool_call_id": "call",
                "error_code": "APPROVAL_REJECTED",
            },
            "reason",
        ),
    ],
)
def test_astral_text_boundaries_match_canonical_and_runtime_wire_validation(
    event_type: str,
    payload: dict[str, object],
    bounded_field: str,
) -> None:
    base = {
        "id": "event",
        "version": "1.0",
        "timestamp": 0,
        "type": event_type,
        "session_id": "session",
        **payload,
    }
    for stored, schema_path, runtime_validator in (
        (False, NEW_EVENT_SCHEMA, validate_new_event_python),
        (True, STORED_EVENT_SCHEMA, validate_stored_event_python),
    ):
        schema = json.loads(schema_path.read_text())
        canonical = Draft202012Validator(schema, format_checker=FormatChecker())
        sequence = {"sequence": 1} if stored else {}
        accepted = {**base, bounded_field: "😀" * 200, **sequence}
        assert canonical.is_valid(accepted)
        runtime_validator(accepted)

        rejected = {**base, bounded_field: "😀" * 201, **sequence}
        assert not canonical.is_valid(rejected)
        with pytest.raises(EventSchemaIncompatibleError) as raised:
            runtime_validator(rejected)
        assert raised.value.path == f"/{bounded_field}"


def test_invalid_wire_fixtures_have_stable_json_pointers() -> None:
    fixtures = json.loads(INVALID_CONFORMANCE_FIXTURE.read_text())["cases"]
    for case in fixtures:
        validator = (
            validate_stored_event_python
            if case["kind"] == "stored"
            else validate_new_event_python
        )
        with pytest.raises(EventSchemaIncompatibleError) as raised:
            validator(case["event"])
        assert raised.value.path == case["path"], case["name"]


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
    ts_types = (
        REPO_ROOT / "kaji" / "packages" / "typescript" / "src" / "events" / "types.ts"
    )
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
    parsed = [validate_stored_event_python(payload) for payload in fixture["events"]]
    drafts = []
    for payload in fixture["events"]:
        draft = dict(payload)
        draft.pop("sequence")
        drafts.append(validate_new_event_python(draft))
    assert isinstance(parsed[0], SessionCreated)
    assert {event.type for event in drafts} == set(EventType)

    stored = parsed
    state = replay_session(stored)

    assert len(stored) == 40
    assert [event.sequence for event in stored] == list(range(1, 41))
    assert {event.type for event in stored} == set(EventType)
    assert all(event.version == "1.0" for event in stored)
    assert all(isinstance(event.timestamp, float) for event in stored)
    assert state.session_id == "session-1"
    assert state.is_active is False
    assert state.pending_approvals == set()


def test_shared_turn_failure_conformance_fixture_is_bounded_and_turn_scoped() -> None:
    fixture = json.loads(CONFORMANCE_FIXTURE.read_text())
    parsed = TypeAdapter(KajiEvent).validate_python(fixture["events"][2])

    assert isinstance(parsed, AgentTurnFailed)
    assert parsed.turn_id == "turn-1"
    assert parsed.error == "Agent turn failed"
    assert parsed.error_code == "TURN_TIMEOUT"
    assert parsed.phase == "provider_stream"

    timeout = AgentTurnFailed(
        session_id="session-1",
        turn_id="turn-1",
        error="Agent turn timed out",
        error_code="TURN_TIMEOUT",
        phase="provider_stream",
        retryable=True,
        outcome="unknown",
    )
    assert timeout.error_code == "TURN_TIMEOUT"
    assert timeout.phase == "provider_stream"
    assert timeout.retryable is True
    assert timeout.outcome == "unknown"

    with pytest.raises(ValidationError):
        TypeAdapter(AgentTurnFailed).validate_python(
            {"session_id": "session-1", "error": "Agent turn failed"}
        )
    with pytest.raises(ValidationError):
        AgentTurnFailed(session_id="session-1", turn_id="turn-1", error="x" * 201)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (ToolCallRequested, {"tool_args": {}}),
        (ToolCallStarted, {}),
        (ToolCallCompleted, {"result": {}}),
        (ToolCallFailed, {"error": "failed"}),
    ],
)
def test_tool_lifecycle_identifiers_match_the_shared_non_empty_contract(
    event_type: type[object],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(event_type).validate_python(
            {
                "session_id": "session",
                "tool_name": "tool",
                "tool_call_id": "call",
                **payload,
            }
        )
    for field in ("tool_name", "tool_call_id"):
        with pytest.raises(ValidationError):
            TypeAdapter(event_type).validate_python(
                {
                    "session_id": "session",
                    "turn_id": "turn",
                    "tool_name": "tool",
                    "tool_call_id": "call",
                    **payload,
                    field: "",
                }
            )

    if event_type is ToolCallFailed:
        with pytest.raises(ValidationError):
            ToolCallFailed(
                session_id="session",
                turn_id="turn",
                tool_name="tool",
                tool_call_id="call",
                error="x" * 201,
            )


def test_approval_rejection_reason_rejects_blank_without_normalizing_text() -> None:
    reason = "  Denied by operator  "
    event = ToolApprovalRejected(
        session_id="session",
        turn_id="turn",
        tool_name="tool",
        tool_call_id="call",
        error_code="APPROVAL_REJECTED",
        reason=reason,
    )
    assert event.reason == reason

    with pytest.raises(ValidationError):
        ToolApprovalRejected(
            session_id="session",
            turn_id="turn",
            tool_name="tool",
            tool_call_id="call",
            error_code="APPROVAL_REJECTED",
            reason="   ",
        )
