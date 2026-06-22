"""AgentKit -- build agentic voice platforms in Python.

Public names are resolved lazily (PEP 562): ``import agentkit`` performs no
heavy submodule imports and requires no environment configured. A name is
imported from its module only when first accessed, e.g.
``from agentkit import EventBus`` or ``agentkit.register_tool``. For lower-level
building blocks, import the relevant subpackage directly (e.g.
``agentkit.modalities.voice.tts``).

Public surface follows PEP 8: classes are CapWords (``AgentRuntime``,
``ToolSpec``) and decorators / function helpers are snake_case (``tool``,
``register_tool``, ``get_provider``).
"""

import importlib
from typing import Any

__version__ = "0.1.0"

# Public name -> module it lives in. Kept as a static map so that importing
# the top-level package triggers no submodule side effects. Entries are
# grouped by category and sorted alphabetically inside each group.
_LAZY: dict[str, str] = {
    # --- Types: classes, dataclasses, protocols, errors ----------------------
    "AgentBuilder": "agentkit.runtime.agents",
    "AgentRuntime": "agentkit.runtime.agents",
    "CancellationToken": "agentkit.runtime.agents",
    "EventBus": "agentkit.infra.events",
    "EventStore": "agentkit.infra.events",
    "InMemoryEventBus": "agentkit.infra.events",
    "InMemoryEventStore": "agentkit.infra.events",
    "Integration": "agentkit.runtime.integrations",
    "ModelProvider": "agentkit.runtime.providers",
    "ProviderAPIError": "agentkit.runtime.providers.errors",
    "ProviderConfigError": "agentkit.runtime.providers.errors",
    "ProviderError": "agentkit.runtime.providers.errors",
    # ReplaySession is actually a function; the CapWords spelling predates the
    # PEP 8 cleanup and is kept here for back-compat. Rename to replay_session
    # would be the consistent fix.
    "ReplaySession": "agentkit.runtime.sessions",
    "SessionManager": "agentkit.runtime.sessions",
    "SessionState": "agentkit.runtime.sessions",
    "ToolContext": "agentkit.runtime.tools.registry",
    "ToolRegistry": "agentkit.runtime.tools.registry",
    "ToolSpec": "agentkit.runtime.tools.registry",
    "UserMessage": "agentkit.infra.events",

    # --- Decorators & registration helpers (PEP 8 snake_case) ----------------
    "function_tool": "agentkit.runtime.integrations",
    "get_provider": "agentkit.runtime.providers",
    "list_tool_specs": "agentkit.runtime.tools.registry",
    "register_provider": "agentkit.runtime.providers",
    "register_tool": "agentkit.runtime.tools.registry",
    "tool": "agentkit.runtime.integrations",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
