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
    "AgentBuilder": "agentkit.runtime.agents",
    "AgentRuntime": "agentkit.runtime.agents",
    "CancellationToken": "agentkit.runtime.agents",
    "EventBus": "agentkit.infra.events",
    "EventStore": "agentkit.infra.events",
    "FunctionTool": "agentkit.runtime.integrations",
    "GetProvider": "agentkit.runtime.providers",
    "InMemoryEventBus": "agentkit.infra.events",
    "InMemoryEventStore": "agentkit.infra.events",
    "Integration": "agentkit.runtime.integrations",
    "ListToolSpecs": "agentkit.runtime.tools.registry",
    "ModelProvider": "agentkit.runtime.providers",
    "ProviderAPIError": "agentkit.runtime.providers.errors",
    "ProviderConfigError": "agentkit.runtime.providers.errors",
    "ProviderError": "agentkit.runtime.providers.errors",
    "RegisterProvider": "agentkit.runtime.providers",
    "RegisterTool": "agentkit.runtime.tools.registry",
    "ReplaySession": "agentkit.runtime.sessions",
    "SessionManager": "agentkit.runtime.sessions",
    "SessionState": "agentkit.runtime.sessions",
    "Tool": "agentkit.runtime.integrations",
    "ToolContext": "agentkit.runtime.tools.registry",
    "ToolRegistry": "agentkit.runtime.tools.registry",
    "ToolSpec": "agentkit.runtime.tools.registry",
    "UserMessage": "agentkit.infra.events",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
