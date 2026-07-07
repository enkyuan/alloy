from kaji.modalities.voice.event_models import (
    AgentResponse,
    DTMFInputEvent,
    UserTranscriptionReceived,
)
from kaji.modalities.voice.event_registry import EventsRegistry


def test_default_event_aliases_resolve_to_event_classes() -> None:
    assert EventsRegistry.get_type("agent.response") is AgentResponse
    assert EventsRegistry.get_type("user.transcription") is UserTranscriptionReceived
    assert EventsRegistry.get_type("dtmf.input") is DTMFInputEvent


def test_default_event_classes_resolve_to_aliases() -> None:
    assert EventsRegistry.get_alias(AgentResponse) == "agent.response"
    assert EventsRegistry.get_alias(UserTranscriptionReceived) == "user.transcription"
    assert EventsRegistry.get_alias(DTMFInputEvent) == "dtmf.input"


def test_unknown_alias_returns_none() -> None:
    assert EventsRegistry.get_type("does.not.exist") is None


def test_custom_event_registration_round_trips() -> None:
    class CustomEvent:
        pass

    alias = "custom.test_event"
    try:
        EventsRegistry.register(alias, CustomEvent)

        assert EventsRegistry.get_type(alias) is CustomEvent
        assert EventsRegistry.get_alias(CustomEvent) == alias
    finally:
        EventsRegistry.aliases.pop(alias, None)
        EventsRegistry.events.pop(CustomEvent, None)
