"""AgentKit — build agentic voice platforms in Python.

Public names are resolved lazily (PEP 562): ``import agentkit`` performs no
heavy submodule imports and requires no environment configured. A name is
imported from its module only when first accessed, e.g. ``from agentkit import
EventBus`` or ``agentkit.RegisterTool``. For lower-level building blocks,
import the relevant subpackage directly (e.g. ``agentkit.modalities.voice.tts``).
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
    "EventBusProtocol": "agentkit.infra.events",
    "EventStore": "agentkit.infra.events",
    "EventType": "agentkit.infra.events",
    "InMemoryEventBus": "agentkit.infra.events",
    "InMemoryEventStore": "agentkit.infra.events",
    "UserMessage": "agentkit.infra.events",
    # Agent runtime
    "AgentRuntime": "agentkit.runtime.agents",
    "AgentStrategy": "agentkit.runtime.agents",
    "CancellationToken": "agentkit.runtime.agents",
    "AgentBuilder": "agentkit.runtime.agents",
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
    "GetProvider": "agentkit.runtime.providers",
    "RegisterProvider": "agentkit.runtime.providers",
    # Integrations
    "Integration": "agentkit.runtime.integrations",
    "Tool": "agentkit.runtime.integrations",
    # Toolgen
    "ToolSpec": "agentkit.runtime.tools.registry",
    "ToolContext": "agentkit.runtime.tools.registry",
    "ToolRegistry": "agentkit.runtime.tools.registry",
    "RegisterTool": "agentkit.runtime.tools.registry",
    "ListToolSpecs": "agentkit.runtime.tools.registry",
    "ToolSpecFromModel": "agentkit.runtime.tools.registry",
    "ExecuteTool": "agentkit.runtime.tools.registry",
    "ClearTools": "agentkit.runtime.tools.registry",
    "ToolPolicy": "agentkit.runtime.tools.policies",
    "ToolPolicyViolation": "agentkit.runtime.tools.policies",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
