import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union  # noqa: F401

from pydantic import BaseModel, ConfigDict, Field

from kaji.infra.events.types import EventType


class BaseEvent(BaseModel):
    """Base class for all Kaji events.

    No provider-specific or voice-specific fields in the base type.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0"
    timestamp: float = Field(default_factory=time.time)
    session_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


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


class ToolCallRequested(BaseEvent):
    type: Literal[EventType.TOOL_CALL_REQUESTED] = EventType.TOOL_CALL_REQUESTED
    tool_name: str
    tool_args: Dict[str, Any]
    tool_call_id: str


class ToolCallStarted(BaseEvent):
    type: Literal[EventType.TOOL_CALL_STARTED] = EventType.TOOL_CALL_STARTED
    tool_name: str
    tool_call_id: str


class ToolCallCompleted(BaseEvent):
    type: Literal[EventType.TOOL_CALL_COMPLETED] = EventType.TOOL_CALL_COMPLETED
    tool_name: str
    tool_call_id: str
    result: Any
    tokens: Optional[EventTokenUsage] = None
    cost_usd: Optional[float] = Field(default=None, ge=0)


class ToolCallFailed(BaseEvent):
    type: Literal[EventType.TOOL_CALL_FAILED] = EventType.TOOL_CALL_FAILED
    tool_name: str
    tool_call_id: str
    error: str


class ToolApprovalRequested(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_REQUESTED] = EventType.TOOL_APPROVAL_REQUESTED
    tool_name: str
    tool_call_id: str
    tool_args: Dict[str, Any]
    risk: Optional[str] = None


class ToolApprovalApproved(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_APPROVED] = EventType.TOOL_APPROVAL_APPROVED
    tool_name: str
    tool_call_id: str


class ToolApprovalRejected(BaseEvent):
    type: Literal[EventType.TOOL_APPROVAL_REJECTED] = EventType.TOOL_APPROVAL_REJECTED
    tool_name: str
    tool_call_id: str
    reason: Optional[str] = None


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


KajiEvent = Union[
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
]
