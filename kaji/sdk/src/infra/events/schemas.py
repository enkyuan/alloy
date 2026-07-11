from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from importlib import resources
import json
import re
from typing import (  # noqa: F401
    Annotated,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    TypeAlias,
    Union,
    cast,
    runtime_checkable,
)

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from jsonschema.protocols import Validator as JsonSchemaValidator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.json import canonical_json
from kaji.infra.events.types import EventType
from kaji.runtime.determinism import (
    Clock,
    IdFactory,
    SYSTEM_CLOCK,
    SYSTEM_ID_FACTORY,
)


_EVENT_ID_FACTORY: ContextVar[IdFactory] = ContextVar(
    "kaji_event_id_factory", default=SYSTEM_ID_FACTORY
)
_EVENT_CLOCK: ContextVar[Clock] = ContextVar("kaji_event_clock", default=SYSTEM_CLOCK)
MAX_DURABLE_TOOL_ARGUMENT_BYTES = 64 * 1024
_REQUIRED_WIRE_FIELDS = ("id", "version", "timestamp", "type", "session_id")


def durable_tool_arguments_size(value: Dict[str, Any]) -> int:
    return len(canonical_json(value, subject="tool arguments").encode("utf-8"))


def _validate_durable_tool_arguments(value: Dict[str, Any]) -> Dict[str, Any]:
    try:
        size = durable_tool_arguments_size(value)
    except (TypeError, ValueError):
        raise ValueError("tool_args must contain only JSON values") from None
    if size > MAX_DURABLE_TOOL_ARGUMENT_BYTES:
        raise ValueError(
            "tool_args cannot exceed 65536 serialized bytes; payload redacted"
        )
    return value


def _next_event_id() -> str:
    return _EVENT_ID_FACTORY.get().next("event")


def _event_wall_time() -> float:
    return _EVENT_CLOCK.get().now_wall_seconds()


def _bounded_unicode_text(value: str, field: str) -> str:
    if len(value) > 200:
        raise ValueError(f"{field} must contain at most 200 Unicode code points")
    return value


@contextmanager
def event_defaults(id_factory: IdFactory, clock: Clock):
    """Scope Pydantic event defaults to one async task/runtime operation."""
    id_token = _EVENT_ID_FACTORY.set(id_factory)
    clock_token = _EVENT_CLOCK.set(clock)
    try:
        yield
    finally:
        _EVENT_CLOCK.reset(clock_token)
        _EVENT_ID_FACTORY.reset(id_token)


class BaseEvent(BaseModel):
    """Base class for all Kaji events.

    No provider-specific or voice-specific fields in the base type.
    """

    id: str = Field(
        default_factory=_next_event_id,
        min_length=1,
        validate_default=True,
    )
    version: Literal["1.0"] = "1.0"
    timestamp: float = Field(default_factory=_event_wall_time)
    session_id: str = Field(min_length=1)
    turn_id: Optional[str] = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    metadata: Dict[str, JsonValue] = Field(default_factory=dict)
    sequence: Optional[int] = Field(
        default=None, ge=1, exclude_if=lambda value: value is None
    )

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_is_durable_json(cls, value: Any) -> Any:
        canonical_json(value, subject="event metadata")
        return value


class SessionCreated(BaseEvent):
    type: Literal[EventType.SESSION_CREATED] = EventType.SESSION_CREATED


class SessionClosed(BaseEvent):
    type: Literal[EventType.SESSION_CLOSED] = EventType.SESSION_CLOSED
    reason: Optional[str] = None


class UserMessage(BaseEvent):
    type: Literal[EventType.USER_MESSAGE] = EventType.USER_MESSAGE
    content: str


class UserAudioChunk(BaseEvent):
    type: Literal[EventType.USER_AUDIO_CHUNK] = EventType.USER_AUDIO_CHUNK
    chunk_size_bytes: int


class TranscriptPartial(BaseEvent):
    type: Literal[EventType.TRANSCRIPT_PARTIAL] = EventType.TRANSCRIPT_PARTIAL
    text: str


class TranscriptFinal(BaseEvent):
    type: Literal[EventType.TRANSCRIPT_FINAL] = EventType.TRANSCRIPT_FINAL
    text: str


class MemoryRetrievalStarted(BaseEvent):
    type: Literal[EventType.MEMORY_RETRIEVAL_STARTED] = (
        EventType.MEMORY_RETRIEVAL_STARTED
    )
    query: str


class MemoryRetrievalCompleted(BaseEvent):
    type: Literal[EventType.MEMORY_RETRIEVAL_COMPLETED] = (
        EventType.MEMORY_RETRIEVAL_COMPLETED
    )
    query: str
    documents: List[Dict[str, Any]]


class AgentReasoningStarted(BaseEvent):
    type: Literal[EventType.AGENT_REASONING_STARTED] = EventType.AGENT_REASONING_STARTED


class AgentMessageDelta(BaseEvent):
    type: Literal[EventType.AGENT_MESSAGE_DELTA] = EventType.AGENT_MESSAGE_DELTA
    delta: str


class EventTokenUsage(BaseModel):
    input: int = Field(ge=0)
    output: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class AgentMessageCompleted(BaseEvent):
    type: Literal[EventType.AGENT_MESSAGE_COMPLETED] = EventType.AGENT_MESSAGE_COMPLETED
    content: str
    tokens: Optional[EventTokenUsage] = None
    cost_usd: Optional[float] = Field(default=None, ge=0)


class AgentTurnExhausted(BaseEvent):
    type: Literal[EventType.AGENT_TURN_EXHAUSTED] = EventType.AGENT_TURN_EXHAUSTED
    max_iterations: int = Field(ge=0)
    pending_tool_calls: List[Dict[str, Any]]
    reason: Optional[str] = None


class AgentTurnFailed(BaseEvent):
    type: Literal[EventType.AGENT_TURN_FAILED] = EventType.AGENT_TURN_FAILED
    turn_id: str = Field(min_length=1)
    error: str = Field(min_length=1)

    @field_validator("error")
    @classmethod
    def _bounded_error(cls, value: str) -> str:
        return _bounded_unicode_text(value, "error")


class ToolCallRequested(BaseEvent):
    type: Literal[EventType.TOOL_CALL_REQUESTED] = EventType.TOOL_CALL_REQUESTED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_args: Dict[str, Any]
    tool_call_id: str = Field(min_length=1)

    @field_validator("tool_args", mode="before")
    @classmethod
    def _bounded_tool_args(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("tool_args must be a JSON object")
        return _validate_durable_tool_arguments(value)


class ToolCallStarted(BaseEvent):
    type: Literal[EventType.TOOL_CALL_STARTED] = EventType.TOOL_CALL_STARTED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)


class ToolCallCompleted(BaseEvent):
    type: Literal[EventType.TOOL_CALL_COMPLETED] = EventType.TOOL_CALL_COMPLETED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    result: Any
    tokens: Optional[EventTokenUsage] = None
    cost_usd: Optional[float] = Field(default=None, ge=0)


class ToolCallFailed(BaseEvent):
    type: Literal[EventType.TOOL_CALL_FAILED] = EventType.TOOL_CALL_FAILED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    error: str = Field(min_length=1)
    error_code: Optional[str] = Field(
        default=None, exclude_if=lambda value: value is None
    )
    error_path: Optional[str] = Field(
        default=None, exclude_if=lambda value: value is None
    )
    retryable: Optional[bool] = Field(
        default=None, exclude_if=lambda value: value is None
    )
    outcome: Optional[Literal["not_started", "failed", "unknown"]] = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @field_validator("error")
    @classmethod
    def _bounded_error(cls, value: str) -> str:
        return _bounded_unicode_text(value, "error")


class ToolApprovalRequested(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_REQUESTED] = EventType.TOOL_APPROVAL_REQUESTED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tool_args: Dict[str, Any]
    risk: Literal["read", "write", "external_effect", "destructive", "admin"]

    @field_validator("tool_args", mode="before")
    @classmethod
    def _bounded_tool_args(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("tool_args must be a JSON object")
        return _validate_durable_tool_arguments(value)


class ToolApprovalApproved(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_APPROVED] = EventType.TOOL_APPROVAL_APPROVED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)


class ToolApprovalRejected(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_REJECTED] = EventType.TOOL_APPROVAL_REJECTED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    error_code: Literal[
        "APPROVAL_REJECTED",
        "APPROVAL_TIMEOUT",
        "TOOL_CANCELLED",
        "APPROVAL_UNAVAILABLE",
    ]
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _reason_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval rejection reason must not be blank")
        return _bounded_unicode_text(value, "reason")


class WorkflowStarted(BaseEvent):
    type: Literal[EventType.WORKFLOW_STARTED] = EventType.WORKFLOW_STARTED
    workflow_name: str


class WorkflowCompleted(BaseEvent):
    type: Literal[EventType.WORKFLOW_COMPLETED] = EventType.WORKFLOW_COMPLETED
    workflow_name: str
    result: Any


class WorkflowFailed(BaseEvent):
    type: Literal[EventType.WORKFLOW_FAILED] = EventType.WORKFLOW_FAILED
    workflow_name: str
    error: str


class CancellationRequested(BaseEvent):
    type: Literal[EventType.CANCELLATION_REQUESTED] = EventType.CANCELLATION_REQUESTED
    reason: str


class CancellationCompleted(BaseEvent):
    type: Literal[EventType.CANCELLATION_COMPLETED] = EventType.CANCELLATION_COMPLETED


KajiEvent = Annotated[
    Union[
        SessionCreated,
        SessionClosed,
        UserMessage,
        UserAudioChunk,
        TranscriptPartial,
        TranscriptFinal,
        MemoryRetrievalStarted,
        MemoryRetrievalCompleted,
        AgentReasoningStarted,
        AgentMessageDelta,
        AgentMessageCompleted,
        AgentTurnExhausted,
        AgentTurnFailed,
        ToolCallRequested,
        ToolCallStarted,
        ToolCallCompleted,
        ToolCallFailed,
        ToolApprovalRequested,
        ToolApprovalApproved,
        ToolApprovalRejected,
        WorkflowStarted,
        WorkflowCompleted,
        WorkflowFailed,
        CancellationRequested,
        CancellationCompleted,
    ],
    Field(discriminator="type"),
]

_EVENT_ADAPTER = TypeAdapter(
    KajiEvent,
    config=ConfigDict(hide_input_in_errors=True),
)


def _json_pointer(parts: Any) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _load_wire_schema(filename: str) -> dict[str, Any]:
    package_file = resources.files("kaji.contracts.events").joinpath(filename)
    return json.loads(package_file.read_text(encoding="utf-8"))


_NEW_EVENT_SCHEMA = _load_wire_schema("new-kaji-event-v1.schema.json")
_STORED_EVENT_SCHEMA = _load_wire_schema("stored-kaji-event-v1.schema.json")
_NEW_EVENT_VALIDATOR = Draft202012Validator(
    _NEW_EVENT_SCHEMA, format_checker=FormatChecker()
)
_STORED_EVENT_VALIDATOR = Draft202012Validator(
    _STORED_EVENT_SCHEMA, format_checker=FormatChecker()
)


def _schema_def_name(event_type: str) -> str:
    head, *tail = event_type.split(".")
    return head + "".join(part.title() for part in tail)


@lru_cache(maxsize=50)
def _variant_validator(stored: bool, event_type: str) -> JsonSchemaValidator:
    schema = _STORED_EVENT_SCHEMA if stored else _NEW_EVENT_SCHEMA
    selected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{_schema_def_name(event_type)}",
    }
    return Draft202012Validator(selected, format_checker=FormatChecker())


def _flatten_schema_errors(
    error: JsonSchemaValidationError,
) -> list[JsonSchemaValidationError]:
    flattened = [error]
    for child in error.context:
        flattened.extend(_flatten_schema_errors(child))
    return flattened


def _schema_error_pointer(error: JsonSchemaValidationError) -> str:
    parts = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = next(
            (field for field in error.validator_value if field not in error.instance),
            None,
        )
        if missing is not None:
            parts.append(missing)
    elif error.validator in {"additionalProperties", "unevaluatedProperties"}:
        unexpected = sorted(set(re.findall(r"'([^']+)'", error.message)))
        if unexpected:
            parts.append(unexpected[0])
    return _json_pointer(parts)


def _first_schema_error_pointer(value: dict[str, Any], *, stored: bool) -> str | None:
    validator = _STORED_EVENT_VALIDATOR if stored else _NEW_EVENT_VALIDATOR
    errors = list(validator.iter_errors(value))
    if not errors:
        return None

    event_type = value.get("type")
    if isinstance(event_type, str) and event_type in {item.value for item in EventType}:
        selected_errors = list(
            _variant_validator(stored, event_type).iter_errors(value)
        )
        if selected_errors:
            errors = selected_errors

    candidates = [
        (_schema_error_pointer(item), list(item.absolute_schema_path))
        for error in errors
        for item in _flatten_schema_errors(error)
        if item.validator not in {"allOf", "oneOf", "unevaluatedProperties"}
    ]
    if not candidates:
        return "/"
    return min(candidates, key=lambda item: (item[0] == "/", item[0], item[1]))[0]


def _wire_preflight(value: object, *, stored: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EventSchemaIncompatibleError("/")
    document = cast(dict[str, Any], value)
    for field in _REQUIRED_WIRE_FIELDS:
        if field not in document:
            raise EventSchemaIncompatibleError(f"/{field}")
    for field in ("id", "session_id", "turn_id"):
        if field in document and document[field] == "":
            raise EventSchemaIncompatibleError(f"/{field}")
    if stored and "sequence" not in document:
        raise EventSchemaIncompatibleError("/sequence")
    if not stored and "sequence" in document:
        raise EventSchemaIncompatibleError("/sequence")
    event_type = document.get("type")
    if event_type not in {item.value for item in EventType}:
        raise EventSchemaIncompatibleError("/type")
    schema = _STORED_EVENT_SCHEMA if stored else _NEW_EVENT_SCHEMA
    variant = schema["$defs"][_schema_def_name(cast(str, event_type))]
    allowed = set(schema["$defs"]["base"]["properties"])
    allowed.update(variant["allOf"][1]["properties"])
    unexpected = sorted(set(document) - allowed)
    if unexpected:
        raise EventSchemaIncompatibleError(_json_pointer([unexpected[0]]))
    return document


def _pydantic_error_pointer(error: ValidationError) -> str:
    location = list(error.errors(include_input=False)[0]["loc"])
    if location and location[0] in {item.value for item in EventType}:
        location.pop(0)
    return _json_pointer(location)


def _validate_wire_event(value: object, *, stored: bool) -> KajiEvent:
    document = _wire_preflight(value, stored=stored)
    schema_path = _first_schema_error_pointer(document, stored=stored)
    if schema_path is not None:
        raise EventSchemaIncompatibleError(schema_path)
    try:
        canonical_json(document, subject="event")
        return _EVENT_ADAPTER.validate_python(document)
    except EventSchemaIncompatibleError:
        raise
    except ValidationError as error:
        raise EventSchemaIncompatibleError(_pydantic_error_pointer(error)) from None
    except (TypeError, ValueError):
        raise EventSchemaIncompatibleError("/") from None


def validate_event_python(value: object) -> KajiEvent:
    """Construct an event through the closed union, applying authoring defaults."""
    return _EVENT_ADAPTER.validate_python(value)


def validate_event_json(value: str | bytes | bytearray) -> KajiEvent:
    """Validate a serialized event without applying missing wire-field defaults."""
    try:
        document = json.loads(value)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EventSchemaIncompatibleError("/") from None
    return _validate_wire_event(
        document,
        stored=isinstance(document, dict) and "sequence" in document,
    )


def validate_new_event_python(value: object) -> "NewKajiEvent":
    """Validate an untouched new-event mapping against the frozen wire contract."""
    return require_new_event(_validate_wire_event(value, stored=False))


def validate_stored_event_python(value: object) -> "StoredKajiEvent":
    """Validate an untouched stored-event mapping against the frozen wire contract."""
    return require_stored_event(_validate_wire_event(value, stored=True))


def validate_new_event_json(value: str | bytes | bytearray) -> "NewKajiEvent":
    try:
        document = json.loads(value)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EventSchemaIncompatibleError("/") from None
    return validate_new_event_python(document)


def validate_stored_event_json(value: str | bytes | bytearray) -> "StoredKajiEvent":
    try:
        document = json.loads(value)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EventSchemaIncompatibleError("/") from None
    return validate_stored_event_python(document)


# Python keeps one discriminated event model family for compatibility. These
# names make the persistence boundary explicit without duplicating that model
# hierarchy. The checked cast in ``require_stored_event`` is the only way a
# draft model becomes the distinct stored-event static type.
NewKajiEvent: TypeAlias = KajiEvent


@runtime_checkable
class StoredKajiEvent(Protocol):
    id: str
    version: Literal["1.0"]
    timestamp: float
    session_id: str
    turn_id: Optional[str]
    metadata: Dict[str, Any]
    type: EventType
    sequence: int

    def model_dump(self, **kwargs: Any) -> Dict[str, Any]: ...

    def model_dump_json(self, **kwargs: Any) -> str: ...

    def __getattr__(self, name: str) -> Any: ...


def require_new_event(event: KajiEvent) -> NewKajiEvent:
    if event.sequence is not None:
        raise ValueError("new events must not carry a sequence")
    return event


def revalidate_new_event(event: object) -> NewKajiEvent:
    """Detach and fully revalidate a mutable draft at a durable boundary."""
    value = event.model_dump(mode="python") if isinstance(event, BaseEvent) else event
    return validate_new_event_python(value)


def require_stored_event(event: KajiEvent | StoredKajiEvent) -> StoredKajiEvent:
    if not isinstance(event.sequence, int) or event.sequence < 1:
        raise ValueError("stored events require a positive sequence")
    return cast(StoredKajiEvent, event)


def revalidate_stored_event(
    event: object,
) -> StoredKajiEvent:
    """Detach and fully revalidate a store result before replay or delivery."""
    value = event.model_dump(mode="python") if isinstance(event, BaseEvent) else event
    return validate_stored_event_python(value)
