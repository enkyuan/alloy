import pytest

from sdk.events.voice_models import AgentResponse, DTMFOutputEvent
from sdk.modalities.voice.tts import TTSNotConfiguredError, VoiceTTSAdapter
from sdk.modalities.voice.turn_detection import TurnEndPolicy, resolve_turn_policy
from sdk.modalities.voice.utils.dtmf_lookahead_buffer import (
    DTMFLookAheadCharacterBuffer,
    DTMFLookAheadStringBuffer,
)
from sdk.modalities.voice.utils.phone_numbers import is_e164_phone_number


@pytest.mark.parametrize(
    "number,expected",
    [
        ("+14155552671", True),
        ("+1234", False),
        ("14155552671", False),
        ("+1-415-555-2671", False),
        ("", False),
    ],
)
def test_is_e164_phone_number(number: str, expected: bool):
    assert is_e164_phone_number(number) is expected


def test_dtmf_lookahead_emits_digit_events():
    buffer = DTMFLookAheadStringBuffer()
    outputs = list(buffer.feed("press dtmf=12 now"))
    dtmf = [item for item in outputs if isinstance(item, DTMFOutputEvent)]
    text = [item for item in outputs if isinstance(item, AgentResponse)]
    assert [event.button for event in dtmf] == ["1", "2"]
    assert any("press" in response.content for response in text)


def test_turn_detection_manual_end_wins():
    assert resolve_turn_policy(explicit_end_signal=True, endpoint_detected=False)


def test_turn_end_policy_values():
    assert TurnEndPolicy.ENDPOINT.value == "endpoint"


@pytest.mark.asyncio
async def test_voice_tts_not_configured():
    adapter = VoiceTTSAdapter()
    with pytest.raises(TTSNotConfiguredError, match="not configured"):
        await adapter.synthesize("hello")


@pytest.mark.asyncio
async def test_voice_tts_rejects_empty_text():
    adapter = VoiceTTSAdapter()
    with pytest.raises(ValueError, match="empty"):
        await adapter.synthesize("   ")


def test_dtmf_character_buffer_flush_pending_text():
    buffer = DTMFLookAheadCharacterBuffer()
    for char in "hello":
        list(buffer.feed(char))
    flushed = list(buffer.flush())
    assert flushed == [AgentResponse(content="hello")]
