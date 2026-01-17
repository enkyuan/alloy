"""
Typed event definitions for the Hermes agent bus system.

These events are serialized to JSON/Redis across the distributed system.
Ported from line/events.py.
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


class ToolResult(BaseModel):
    """Tool execution result."""
    tool_name: str = ""
    tool_args: dict = Field(default_factory=dict)
    result: Optional[object] = None
    error: Optional[str] = None
    metadata: Optional[Dict] = None
    tool_call_id: Optional[str] = None

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


class EndCall(BaseModel):
    """End the call."""
    pass


class AgentGenerationComplete(BaseModel):
    """Agent generation completion event."""
    pass


class AgentError(BaseModel):
    """Send error message to user."""
    error: str
    code: Optional[str] = None


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


class AgentSpeechSent(BaseModel):
    """Agent speech content sent event."""
    content: str


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
            cls._instance.aliases = {} # Dict[str, EventType]
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
# Add more as needed
