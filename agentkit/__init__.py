"""AgentKit — build agentic voice platforms in Python.

Public names are resolved lazily (PEP 562): ``import agentkit`` performs no
heavy submodule imports and requires no environment configured. A name is
imported from its module only when first accessed, e.g. ``from agentkit import
EventBus`` or ``agentkit.register_tool``. For lower-level building blocks,
import the relevant subpackage directly (e.g. ``agentkit.voice.stt``).
"""

import importlib
from typing import Any

__version__ = "0.1.0"

# Public name -> module it lives in. Kept as a static map so that importing
# the top-level package triggers no submodule side effects.
_LAZY: dict[str, str] = {
    # Events
    "AgentKitEvent": "agentkit.events",
    "BaseEvent": "agentkit.events",
    "EventBus": "agentkit.events",
    "EventStore": "agentkit.events",
    "EventType": "agentkit.events",
    "InMemoryEventStore": "agentkit.events",
    # Sessions
    "ReplaySession": "agentkit.sessions",
    "SessionManager": "agentkit.sessions",
    "SessionState": "agentkit.sessions",
    # Providers
    "get_provider": "agentkit.providers",
    "register_provider": "agentkit.providers",
    # Voice / TTS
    "TTSProvider": "agentkit.voice.tts",
    "VoiceTTSAdapter": "agentkit.voice.tts",
    "get_tts_provider": "agentkit.voice.tts",
    # Toolgen
    "ToolSpec": "agentkit.tools.registry",
    "ToolContext": "agentkit.tools.registry",
    "register_tool": "agentkit.tools.registry",
    "list_tool_specs": "agentkit.tools.registry",
    "tool_spec_from_model": "agentkit.tools.registry",
    "execute_tool": "agentkit.tools.registry",
    # Tool retrieval
    "ToolRetriever": "agentkit.tools.retriever",
    "get_tool_retriever": "agentkit.tools.retriever",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
