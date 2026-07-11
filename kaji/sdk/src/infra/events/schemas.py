from contextvars import ContextVar
from contextlib import contextmanager
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

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

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

    id: str = Field(default_factory=_next_event_id)
    version: Literal["1.0"] = "1.0"
    timestamp: float = Field(default_factory=_event_wall_time)
    session_id: str = Field(min_length=1)
    turn_id: Optional[str] = Field(
        default=None, min_length=1, exclude_if=lambda value: value is None
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sequence: Optional[int] = Field(
        default=None, ge=1, exclude_if=lambda value: value is None
    )

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


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
    max_iterations: int
    pending_tool_calls: List[Dict[str, Any]]
    reason: Optional[str] = None


class AgentTurnFailed(BaseEvent):
    type: Literal[EventType.AGENT_TURN_FAILED] = EventType.AGENT_TURN_FAILED
    turn_id: str = Field(min_length=1)
    error: str = Field(min_length=1, max_length=200)


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
    error: str = Field(min_length=1, max_length=200)
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


class ToolApprovalRequested(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_REQUESTED] = EventType.TOOL_APPROVAL_REQUESTED
    turn_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_call_id: str = Field(min_length=1)
    tool_args: Dict[str, Any]
    risk: Literal[
        "read", "write", "external_effect", "financial", "destructive", "admin"
    ]

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
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def _reason_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("approval rejection reason must not be blank")
        return value


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


def validate_event_python(value: object) -> KajiEvent:
    """Validate a Python value against the closed Kaji event union."""
    return _EVENT_ADAPTER.validate_python(value)


def validate_event_json(value: str | bytes | bytearray) -> KajiEvent:
    """Validate JSON against the closed Kaji event union."""
    return _EVENT_ADAPTER.validate_json(value)


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


def revalidate_new_event(event: KajiEvent) -> NewKajiEvent:
    """Detach and fully revalidate a mutable draft at a durable boundary."""
    if not isinstance(event, BaseEvent):
        raise TypeError("new events must be validated Kaji event models")
    validated = validate_event_python(event.model_dump(mode="python"))
    return require_new_event(validated)


def require_stored_event(event: KajiEvent | StoredKajiEvent) -> StoredKajiEvent:
    if not isinstance(event.sequence, int) or event.sequence < 1:
        raise ValueError("stored events require a positive sequence")
    return cast(StoredKajiEvent, event)


def revalidate_stored_event(
    event: KajiEvent | StoredKajiEvent,
) -> StoredKajiEvent:
    """Detach and fully revalidate a store result before replay or delivery."""
    if not isinstance(event, BaseEvent):
        raise TypeError("stored events must be validated Kaji event models")
    validated = validate_event_python(event.model_dump(mode="python"))
    return require_stored_event(validated)
