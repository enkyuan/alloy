"""
Typed event definitions for the Agent agent bus system.

These events are serialized to JSON/Redis across the distributed system.
Ported from the original agent system events module.
"""

import json
import uuid
from typing import Any, Dict, Optional, Type, TypeVar, Union

from pydantic import BaseModel, Field

T = TypeVar("T")
EventInstance = T
EventType = Type[T]
EventTypeOrAlias = Union[EventType, str]


# --- Core Pydantic Models ---


class AgentResponse(BaseModel):
    """Agent message to be sent to the user."""

    content: str
    chunk_type: str = "text"
    user_id: Optional[str] = None


class ToolResult(BaseModel):
    """Tool execution result."""

    tool_name: str = ""
    tool_args: dict = Field(default_factory=dict)
    result: Optional[object] = None
    error: Optional[str] = None
    metadata: Optional[Dict] = None
    tool_call_id: Optional[str] = None
    user_id: Optional[str] = None

    @property
    def result_str(self) -> Optional[str]:
        if self.result is not None:
            try:
                return json.dumps(self.result)
            except Exception:
                return str(self.result)
        return None

    @property
    def success(self) -> bool:
        return self.error is None


class ToolCall(BaseModel):
    """Tool execution request."""

    tool_name: str
    tool_args: Dict = Field(default_factory=dict)
    tool_call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_response: Dict = Field(default_factory=dict)
    user_id: Optional[str] = None


class EndCall(BaseModel):
    """End the call."""

    @property
    def content(self) -> str:
        """Returns string representation of the end call event."""
        return self.__repr__()


class AgentGenerationComplete(BaseModel):
    """Agent generation completion event."""

    pass


class Authorize(BaseModel):
    """Change the authorized agent."""

    agent: str


class AgentError(BaseModel):
    """Send error message to user."""

    error: str
    code: Optional[str] = None
    user_id: Optional[str] = None


class AgentStartedSpeaking(BaseModel):
    """Agent started speaking event."""

    pass


class AgentStoppedSpeaking(BaseModel):
    """Agent stopped speaking event."""

    pass


class UserStartedSpeaking(BaseModel):
    """User started speaking event."""

    pass


class UserStoppedSpeaking(BaseModel):
    """User stopped speaking event."""

    pass


class UserTranscriptionReceived(BaseModel):
    """User transcription received event."""

    content: str
    user_id: Optional[str] = None


class AgentSpeechSent(BaseModel):
    """Agent speech content sent event."""

    content: str


class UserUnknownInputReceived(BaseModel):
    """User unknown input received event."""

    input_data: str


class CustomReceived(BaseModel):
    """Custom event received with arbitrary metadata."""

    metadata: Dict[str, Any]


class LogMetric(BaseModel):
    """Log metric event for tracking usage metrics."""

    name: str
    value: Any


class DTMFInputEvent(BaseModel):
    """DTMF event for tracking input."""

    button: str


class DTMFOutputEvent(BaseModel):
    """DTMF event for tracking output."""

    button: str


class DTMFStoppedEvent(BaseModel):
    """DTMF stopped event for tracking DTMF input."""

    pass


class TransferCall(BaseModel):
    """Initiate transfer call to destination."""

    target_phone_number: str
    timeout_s: Optional[int] = 30


class AgentHandoff(BaseModel):
    """Agent handoff event for transfer_to_* patterns."""

    target_agent: str
    reason: str = ""


# --- Registry for Redis Deserialization ---


class _EventsRegistry:
    """A singleton registry of all events.
    Used to deserialize JSON from Redis back into Pydantic models.
    """

    _instance: Optional["_EventsRegistry"] = None
    events: Dict[EventType, str]
    aliases: Dict[str, EventType]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.events = {}  # Dict[EventType, str]
            cls._instance.aliases = {}  # Dict[str, EventType]
        return cls._instance

    def register(self, alias: str, event_type: EventType):
        if event_type in self.events:
            # Allow re-registration for now, or log warning
            pass
        self.events[event_type] = alias
        self.aliases[alias] = event_type

    def get_alias(self, event_type: EventType) -> Optional[str]:
        return self.events.get(event_type, None)

    def get_type(self, alias: str) -> Optional[EventType]:
        return self.aliases.get(alias, None)


EventsRegistry = _EventsRegistry()

# Register core events
EventsRegistry.register("agent.response", AgentResponse)
EventsRegistry.register("tool.call", ToolCall)
EventsRegistry.register("tool.result", ToolResult)
EventsRegistry.register("user.transcription", UserTranscriptionReceived)
EventsRegistry.register("agent.generation_complete", AgentGenerationComplete)
EventsRegistry.register("agent.error", AgentError)
EventsRegistry.register("agent.handoff", AgentHandoff)
EventsRegistry.register("agent.started_speaking", AgentStartedSpeaking)
EventsRegistry.register("agent.stopped_speaking", AgentStoppedSpeaking)
EventsRegistry.register("agent.speech_sent", AgentSpeechSent)
EventsRegistry.register("authorize", Authorize)
EventsRegistry.register("custom.received", CustomReceived)
EventsRegistry.register("dtmf.input", DTMFInputEvent)
EventsRegistry.register("dtmf.output", DTMFOutputEvent)
EventsRegistry.register("dtmf.stopped", DTMFStoppedEvent)
EventsRegistry.register("end.call", EndCall)
EventsRegistry.register("log.metric", LogMetric)
EventsRegistry.register("transfer.call", TransferCall)
EventsRegistry.register("user.started_speaking", UserStartedSpeaking)
EventsRegistry.register("user.stopped_speaking", UserStoppedSpeaking)
EventsRegistry.register("user.unknown_input", UserUnknownInputReceived)
