"""Voice modality — event models, turn helpers, and TTS adapters.

Public names are resolved lazily (PEP 562) so importing this package does not
eagerly construct provider clients or read settings. ``from kaji.modalities.voice
import X`` still works for every name in ``__all__``.
"""

import importlib
from typing import Any

# Public name -> module it lives in. Resolved on first attribute access.
_LAZY: dict[str, str] = {
    "TTSNotConfiguredError": "kaji.modalities.voice.tts",
    "TTSProvider": "kaji.modalities.voice.tts",
    "VoiceTTSAdapter": "kaji.modalities.voice.tts",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
