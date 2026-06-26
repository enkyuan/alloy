"""Kaji -- build agentic voice platforms in Python.

Public names are resolved lazily (PEP 562): ``import kaji`` performs no
heavy submodule imports and requires no environment configured. A name is
imported from its module only when first accessed, e.g.
``from kaji import EventBus`` or ``kaji.register_tool``. For lower-level
building blocks, import the relevant subpackage directly (e.g.
``kaji.modalities.voice.tts``).

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
    "AgentBuilder": "kaji.runtime.agents",
    "AgentRuntime": "kaji.runtime.agents",
    "CancellationToken": "kaji.runtime.agents",
    "EventBus": "kaji.infra.events",
    "EventStore": "kaji.infra.events",
    "InMemoryEventBus": "kaji.infra.events",
    "InMemoryEventStore": "kaji.infra.events",
    "Integration": "kaji.runtime.integrations",
    "ModelProvider": "kaji.runtime.providers",
    "ProviderAPIError": "kaji.runtime.providers.errors",
    "ProviderConfigError": "kaji.runtime.providers.errors",
    "ProviderError": "kaji.runtime.providers.errors",
    "SessionManager": "kaji.runtime.sessions",
    "SessionState": "kaji.runtime.sessions",
    "ToolContext": "kaji.runtime.tools.registry",
    "ToolRegistry": "kaji.runtime.tools.registry",
    "ToolSpec": "kaji.runtime.tools.registry",
    "UnknownToolError": "kaji.runtime.tools.registry",
    "UserMessage": "kaji.infra.events",
    # --- Decorators & registration helpers (PEP 8 snake_case) ----------------
    "function_tool": "kaji.runtime.integrations",
    "get_provider": "kaji.runtime.providers",
    "list_tool_specs": "kaji.runtime.tools.registry",
    "register_provider": "kaji.runtime.providers",
    "register_tool": "kaji.runtime.tools.registry",
    "replay_session": "kaji.runtime.sessions",
    "tool": "kaji.runtime.integrations",
}

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
