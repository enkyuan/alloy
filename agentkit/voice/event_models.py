"""Typed event payload models for the agent bus."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    """Agent message to be sent to the user."""

    content: str
    chunk_type: str = "text"
    user_id: Optional[str] = None


class AgentAudioChunk(BaseModel):
    """A chunk of synthesized agent audio to stream to the user.

    Emitted by the TTS stage as it synthesizes an ``AgentResponse``. ``seq``
    orders chunks within one response so the client can reassemble/play them.
    Audio is base64-encoded so the event survives JSON serialization over the
    Redis envelope and the client WebSocket.
    """

    audio_b64: str
    mime_type: str = "audio/pcm"
    seq: int = 0
    user_id: Optional[str] = None

    @classmethod
    def from_bytes(
        cls,
        audio: bytes,
        *,
        seq: int = 0,
        mime_type: str = "audio/pcm",
        user_id: Optional[str] = None,
    ) -> "AgentAudioChunk":
        """Build a chunk from raw audio bytes, base64-encoding for transport."""
        import base64

        return cls(
            audio_b64=base64.b64encode(audio).decode("ascii"),
            seq=seq,
            mime_type=mime_type,
            user_id=user_id,
        )

    def to_bytes(self) -> bytes:
        """Decode the base64 payload back to raw audio bytes."""
        import base64

        return base64.b64decode(self.audio_b64)


class ToolResult(BaseModel):
    """Tool execution result."""

    tool_name: str = ""
    tool_args: dict = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
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
    alternatives: list[str] = Field(default_factory=list)
    parse_hint: Optional[Dict[str, Any]] = None
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
