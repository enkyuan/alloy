"""Kaji -- build agentic platforms in Python.

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

__version__ = "0.2.0b1"

# Public name -> module it lives in. Kept as a static map so that importing
# the top-level package triggers no submodule side effects. Entries are
# grouped by category and sorted alphabetically inside each group.
_LAZY: dict[str, str] = {
    # --- Types: classes, dataclasses, protocols, errors ----------------------
    "AgentBuilder": "kaji.runtime.agents",
    "AgentRuntime": "kaji.runtime.agents",
    "ApprovalDecision": "kaji.runtime.agents",
    "ApprovalHandler": "kaji.runtime.agents",
    "ApprovalRequestContext": "kaji.runtime.agents",
    "AppendResult": "kaji.infra.events",
    "CancellationToken": "kaji.runtime.agents",
    "Clock": "kaji.runtime.determinism",
    "Chunk": "kaji.knowledge",
    "Document": "kaji.knowledge",
    "DocumentRAG": "kaji.knowledge",
    "DurableJsonLimitError": "kaji.infra.events",
    "Embedder": "kaji.runtime.tools",
    "EmbeddingCache": "kaji.runtime.tools",
    "EffectiveRuntimeLimits": "kaji.runtime.agents",
    "EventBus": "kaji.infra.events",
    "EventBufferOverflowError": "kaji.infra.events",
    "EventDeliveryError": "kaji.infra.events",
    "EventIdConflictError": "kaji.infra.events",
    "EventJournal": "kaji.infra.events",
    "EventApprovalHandler": "kaji.runtime.agents",
    "EventBackedApprovalHandler": "kaji.runtime.agents",
    "EventStoreCapacityError": "kaji.infra.events",
    "EventStore": "kaji.infra.events",
    "HistoryStore": "kaji.runtime.agents",
    "IdFactory": "kaji.runtime.determinism",
    "InMemoryEventBus": "kaji.infra.events",
    "InMemoryEventJournal": "kaji.infra.events",
    "InMemoryEventStore": "kaji.infra.events",
    "InMemoryHistoryStore": "kaji.runtime.agents",
    "InMemoryToolIdempotencyLedger": "kaji.runtime.tools",
    "InMemoryTurnCoordinator": "kaji.runtime.agents",
    "InMemorySessionStore": "kaji.runtime.sessions",
    "InMemoryVectorStore": "kaji.knowledge",
    "InvalidDurableValueError": "kaji.infra.events",
    "Integration": "kaji.runtime.integrations",
    "JournalEventEmitter": "kaji.runtime.agents",
    "ModelProvider": "kaji.runtime.providers",
    "Measurement": "kaji.infra.observability",
    "MetricsSink": "kaji.infra.observability",
    "MissingToolIdentityError": "kaji.runtime.agents",
    "NewKajiEvent": "kaji.infra.events",
    "NOOP_METRICS": "kaji.infra.observability",
    "NOOP_TRACE": "kaji.infra.observability",
    "NormalizedProviderError": "kaji.runtime.providers.errors",
    "ProviderAPIError": "kaji.runtime.providers.errors",
    "ProviderConfigError": "kaji.runtime.providers.errors",
    "ProviderCancellationContractViolation": "kaji.runtime.agents",
    "ProviderError": "kaji.runtime.providers.errors",
    "ProviderOutputLimitError": "kaji.runtime.providers.errors",
    "ProviderResponseLimits": "kaji.runtime.providers",
    "SessionManager": "kaji.runtime.sessions",
    "SessionRecord": "kaji.runtime.sessions",
    "SessionState": "kaji.runtime.sessions",
    "SessionStore": "kaji.runtime.sessions",
    "SplitEventJournal": "kaji.infra.events",
    "StoredKajiEvent": "kaji.infra.events",
    "SystemClock": "kaji.runtime.determinism",
    "SystemIdFactory": "kaji.runtime.determinism",
    "SpanHandle": "kaji.infra.observability",
    "ToolContext": "kaji.runtime.tools.registry",
    "ToolExecutionContext": "kaji.runtime.agents",
    "ToolExecutionController": "kaji.runtime.tools",
    "ToolExecutionError": "kaji.runtime.tools",
    "ToolExecutionLimits": "kaji.runtime.tools",
    "ToolIdempotencyLedger": "kaji.runtime.tools",
    "ToolInvocation": "kaji.runtime.agents",
    "ToolArgumentValidationError": "kaji.runtime.tools",
    "ToolRegistry": "kaji.runtime.tools.registry",
    "ToolRetriever": "kaji.runtime.tools",
    "ToolSchemaValidationError": "kaji.runtime.tools",
    "ToolSchemaValidator": "kaji.runtime.tools",
    "ToolSpec": "kaji.runtime.tools.registry",
    "TurnCoordinator": "kaji.runtime.agents",
    "TurnExecutionLimits": "kaji.runtime.agents",
    "TurnTimeoutError": "kaji.runtime.agents",
    "TurnContext": "kaji.runtime.agents",
    "TurnResult": "kaji.runtime.agents",
    "TraceSink": "kaji.infra.observability",
    "UnknownToolError": "kaji.runtime.tools.registry",
    "UnclassifiedToolRiskError": "kaji.runtime.tools",
    "IdempotencyCapacityExceeded": "kaji.runtime.tools",
    "IdempotencyConflictError": "kaji.runtime.tools",
    "UserMessage": "kaji.infra.events",
    "VectorStore": "kaji.knowledge",
    # --- Decorators & registration helpers (PEP 8 snake_case) ----------------
    "build_tools_payload": "kaji.runtime.tools",
    "function_tool": "kaji.runtime.integrations",
    "get_provider": "kaji.runtime.providers",
    "list_tool_specs": "kaji.runtime.tools.registry",
    "normalize_provider_error": "kaji.runtime.providers.errors",
    "register_provider": "kaji.runtime.providers",
    "register_tool": "kaji.runtime.tools.registry",
    "replay_session": "kaji.runtime.sessions",
    "replay_legacy_session": "kaji.runtime.sessions",
    "spec_to_neutral": "kaji.runtime.tools",
    "to_anthropic": "kaji.runtime.tools",
    "to_gemini": "kaji.runtime.tools",
    "to_openai": "kaji.runtime.tools",
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
