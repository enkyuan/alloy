"""AgentKit — build agentic voice platforms in Python.

Public names are resolved lazily (PEP 562): ``import agentkit`` performs no
heavy submodule imports and requires no environment configured. A name is
imported from its module only when first accessed, e.g. ``from agentkit import
EventBus`` or ``agentkit.register_tool``. For lower-level building blocks,
import the relevant subpackage directly (e.g. ``agentkit.modalities.voice.stt``).
"""

import importlib
from typing import Any

__version__ = "0.1.0"

# Public name -> module it lives in. Kept as a static map so that importing
# the top-level package triggers no submodule side effects.
_LAZY: dict[str, str] = {
    # Events
    "AgentKitEvent": "agentkit.infra.events",
    "BaseEvent": "agentkit.infra.events",
    "EventBus": "agentkit.infra.events",
    "EventStore": "agentkit.infra.events",
    "EventType": "agentkit.infra.events",
    "InMemoryEventBus": "agentkit.infra.events",
    "InMemoryEventStore": "agentkit.infra.events",
    "UserMessage": "agentkit.infra.events",
    # Agent runtime
    "AgentRuntime": "agentkit.runtime.agents",
    "AgentStrategy": "agentkit.runtime.agents",
    "CancellationToken": "agentkit.runtime.agents",
    "ToolPlanner": "agentkit.runtime.agents",
    "ToolExecutor": "agentkit.runtime.agents.planner",
    # Sessions
    "ReplaySession": "agentkit.runtime.sessions",
    "SessionManager": "agentkit.runtime.sessions",
    "SessionState": "agentkit.runtime.sessions",
    "SessionStore": "agentkit.runtime.sessions.store",
    "InMemorySessionStore": "agentkit.runtime.sessions.store",
    "SessionRecord": "agentkit.runtime.sessions.store",
    # Providers
    "ModelProvider": "agentkit.runtime.providers",
    "get_provider": "agentkit.runtime.providers",
    "register_provider": "agentkit.runtime.providers",
    # Voice / TTS
    "TTSProvider": "agentkit.modalities.voice.tts",
    "VoiceTTSAdapter": "agentkit.modalities.voice.tts",
    "get_tts_provider": "agentkit.modalities.voice.tts",
    # Toolgen
    "ToolSpec": "agentkit.runtime.tools.registry",
    "ToolContext": "agentkit.runtime.tools.registry",
    "ToolRegistry": "agentkit.runtime.tools.registry",
    "register_tool": "agentkit.runtime.tools.registry",
    "list_tool_specs": "agentkit.runtime.tools.registry",
    "tool_spec_from_model": "agentkit.runtime.tools.registry",
    "execute_tool": "agentkit.runtime.tools.registry",
    # Tool retrieval
    "ToolRetriever": "agentkit.runtime.tools.retriever",
    "get_tool_retriever": "agentkit.runtime.tools.retriever",
    # Knowledge / document RAG
    "DocumentRAG": "agentkit.knowledge",
    "Document": "agentkit.knowledge",
    "Chunk": "agentkit.knowledge",
    "VectorStore": "agentkit.knowledge",
    "InMemoryVectorStore": "agentkit.knowledge",
    "chunk_text": "agentkit.knowledge",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
