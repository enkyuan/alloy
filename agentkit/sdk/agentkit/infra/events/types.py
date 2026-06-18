from enum import Enum


class EventType(str, Enum):
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"

    USER_MESSAGE = "user.message"
    USER_AUDIO_CHUNK = "user.audio.chunk"

    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"

    MEMORY_RETRIEVAL_STARTED = "memory.retrieval.started"
    MEMORY_RETRIEVAL_COMPLETED = "memory.retrieval.completed"

    AGENT_REASONING_STARTED = "agent.reasoning.started"
    AGENT_MESSAGE_DELTA = "agent.message.delta"
    AGENT_MESSAGE_COMPLETED = "agent.message.completed"

    TOOL_CALL_REQUESTED = "tool.call.requested"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"
    TOOL_CALL_FAILED = "tool.call.failed"

    TOOL_APPROVAL_REQUESTED = "tool.approval.requested"
    TOOL_APPROVAL_APPROVED = "tool.approval.approved"
    TOOL_APPROVAL_REJECTED = "tool.approval.rejected"

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    CANCELLATION_REQUESTED = "cancellation.requested"
    CANCELLATION_COMPLETED = "cancellation.completed"
