"""AgentKit — build agentic voice platforms in Python.

This module exposes the small set of names most callers need. For
provider implementations, voice plumbing, and lower-level building blocks,
import the relevant subpackage directly (e.g. `agentkit.voice.stt`,
`agentkit.events.store`).
"""

from agentkit.events import (
    AgentKitEvent,
    BaseEvent,
    EventBus,
    EventStore,
    EventType,
    InMemoryEventStore,
)
from agentkit.memory import (
    InMemoryMemoryRetriever,
    MemoryQuery,
    MemoryRecord,
    WorkingMemory,
)
from agentkit.providers import get_provider, register_provider
from agentkit.sessions import (
    ReplaySession,
    SessionManager,
    SessionState,
)
from agentkit.voice.tts import TTSProvider, VoiceTTSAdapter

__version__ = "0.1.0"

__all__ = [
    "AgentKitEvent",
    "BaseEvent",
    "EventBus",
    "EventStore",
    "EventType",
    "InMemoryEventStore",
    "InMemoryMemoryRetriever",
    "MemoryQuery",
    "MemoryRecord",
    "ReplaySession",
    "SessionManager",
    "SessionState",
    "TTSProvider",
    "VoiceTTSAdapter",
    "WorkingMemory",
    "__version__",
    "get_provider",
    "register_provider",
]
