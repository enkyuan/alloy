import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from sdk.events.types import EventType


class BaseEvent(BaseModel):
    """Base class for all AgentKit events.

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


class AgentMessageCompleted(BaseEvent):
    type: Literal[EventType.AGENT_MESSAGE_COMPLETED] = EventType.AGENT_MESSAGE_COMPLETED
    content: str


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


class ToolCallFailed(BaseEvent):
    type: Literal[EventType.TOOL_CALL_FAILED] = EventType.TOOL_CALL_FAILED
    tool_name: str
    tool_call_id: str
    error: str


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


class SwarmRunStarted(BaseEvent):
    type: Literal[EventType.SWARM_RUN_STARTED] = EventType.SWARM_RUN_STARTED
    run_id: str


class SwarmAgentSpawned(BaseEvent):
    type: Literal[EventType.SWARM_AGENT_SPAWNED] = EventType.SWARM_AGENT_SPAWNED
    run_id: str
    agent_id: str
    agent_role: str


class SwarmAgentCompleted(BaseEvent):
    type: Literal[EventType.SWARM_AGENT_COMPLETED] = EventType.SWARM_AGENT_COMPLETED
    run_id: str
    agent_id: str
    result: Any


class SwarmAgentFailed(BaseEvent):
    type: Literal[EventType.SWARM_AGENT_FAILED] = EventType.SWARM_AGENT_FAILED
    run_id: str
    agent_id: str
    error: str


class SwarmMergeStarted(BaseEvent):
    type: Literal[EventType.SWARM_MERGE_STARTED] = EventType.SWARM_MERGE_STARTED
    run_id: str


class SwarmMergeCompleted(BaseEvent):
    type: Literal[EventType.SWARM_MERGE_COMPLETED] = EventType.SWARM_MERGE_COMPLETED
    run_id: str
    merged_result: Any


class CancellationRequested(BaseEvent):
    type: Literal[EventType.CANCELLATION_REQUESTED] = EventType.CANCELLATION_REQUESTED
    reason: str


class CancellationCompleted(BaseEvent):
    type: Literal[EventType.CANCELLATION_COMPLETED] = EventType.CANCELLATION_COMPLETED


AgentKitEvent = Union[
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
    ToolCallRequested,
    ToolCallStarted,
    ToolCallCompleted,
    ToolCallFailed,
    WorkflowStarted,
    WorkflowCompleted,
    WorkflowFailed,
    SwarmRunStarted,
    SwarmAgentSpawned,
    SwarmAgentCompleted,
    SwarmAgentFailed,
    SwarmMergeStarted,
    SwarmMergeCompleted,
    CancellationRequested,
    CancellationCompleted,
]
