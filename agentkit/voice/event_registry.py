"""Event registry for alias-to-model mapping."""

from __future__ import annotations

from typing import Dict, Optional, Type, TypeVar, Union

from agentkit.voice.event_models import (
    AgentAudioChunk,
    AgentError,
    AgentGenerationComplete,
    AgentHandoff,
    AgentResponse,
    AgentSpeechSent,
    AgentStartedSpeaking,
    AgentStoppedSpeaking,
    Authorize,
    CustomReceived,
    DTMFInputEvent,
    DTMFOutputEvent,
    DTMFStoppedEvent,
    EndCall,
    LogMetric,
    ToolCall,
    ToolResult,
    TransferCall,
    UserStartedSpeaking,
    UserStoppedSpeaking,
    UserTranscriptionReceived,
    UserUnknownInputReceived,
)

T = TypeVar("T")
EventInstance = T
EventType = Type[T]
EventTypeOrAlias = Union[EventType, str]


class _EventsRegistry:
    """A singleton registry of all events."""

    _instance: Optional["_EventsRegistry"] = None
    events: Dict[EventType, str]
    aliases: Dict[str, EventType]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.events = {}
            cls._instance.aliases = {}
        return cls._instance

    def register(self, alias: str, event_type: EventType) -> None:
        self.events[event_type] = alias
        self.aliases[alias] = event_type

    def get_alias(self, event_type: EventType) -> Optional[str]:
        return self.events.get(event_type, None)

    def get_type(self, alias: str) -> Optional[EventType]:
        return self.aliases.get(alias, None)


def register_default_events(registry: _EventsRegistry) -> None:
    """Register all default event aliases."""
    registry.register("agent.response", AgentResponse)
    registry.register("agent.audio", AgentAudioChunk)
    registry.register("tool.call", ToolCall)
    registry.register("tool.result", ToolResult)
    registry.register("user.transcription", UserTranscriptionReceived)
    registry.register("agent.generation_complete", AgentGenerationComplete)
    registry.register("agent.error", AgentError)
    registry.register("agent.handoff", AgentHandoff)
    registry.register("agent.started_speaking", AgentStartedSpeaking)
    registry.register("agent.stopped_speaking", AgentStoppedSpeaking)
    registry.register("agent.speech_sent", AgentSpeechSent)
    registry.register("authorize", Authorize)
    registry.register("custom.received", CustomReceived)
    registry.register("dtmf.input", DTMFInputEvent)
    registry.register("dtmf.output", DTMFOutputEvent)
    registry.register("dtmf.stopped", DTMFStoppedEvent)
    registry.register("end.call", EndCall)
    registry.register("log.metric", LogMetric)
    registry.register("transfer.call", TransferCall)
    registry.register("user.started_speaking", UserStartedSpeaking)
    registry.register("user.stopped_speaking", UserStoppedSpeaking)
    registry.register("user.unknown_input", UserUnknownInputReceived)


EventsRegistry = _EventsRegistry()
register_default_events(EventsRegistry)
