"""Voice modality — STT, TTS, and streaming helpers.

Public names are resolved lazily (PEP 562) so importing this package does not
eagerly construct the Soniox singleton or read settings. ``from agentkit.modalities.voice
import X`` still works for every name in ``__all__``.
"""

import importlib
from typing import Any

# Public name -> module it lives in. Resolved on first attribute access.
_LAZY: dict[str, str] = {
    "TranscriptionSessionState": "agentkit.modalities.voice.stt",
    "authenticate_ws": "agentkit.modalities.voice.stt",
    "process_client_messages": "agentkit.modalities.voice.stt",
    "safe_send_json": "agentkit.modalities.voice.stt",
    "send_error_message": "agentkit.modalities.voice.stt",
    "stream_agent_updates": "agentkit.modalities.voice.stt",
    "connect_soniox": "agentkit.modalities.voice.stt.soniox_gateway",
    "listen_to_soniox": "agentkit.modalities.voice.stt.soniox_gateway",
    "SonioxService": "agentkit.modalities.voice.stt.soniox_service",
    "soniox_service": "agentkit.modalities.voice.stt.soniox_service",
    "TTSNotConfiguredError": "agentkit.modalities.voice.tts",
    "TTSProvider": "agentkit.modalities.voice.tts",
    "VoiceTTSAdapter": "agentkit.modalities.voice.tts",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
