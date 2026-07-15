"""Agent runtime: the provider-agnostic ReAct loop and its building blocks."""

import importlib
from typing import Any


_LAZY: dict[str, str] = {
    "AgentBuilder": "kaji.runtime.agents.builder",
    "AgentRuntime": "kaji.runtime.agents.runtime",
    "AgentStrategy": "kaji.runtime.agents.strategy",
    "ApprovalDecision": "kaji.runtime.agents.approval",
    "ApprovalHandler": "kaji.runtime.agents.approval",
    "ApprovalRequestContext": "kaji.runtime.agents.approval",
    "CancellationToken": "kaji.runtime.agents.cancellation",
    "ContextDiagnostics": "kaji.runtime.agents.context",
    "ContextIntegrityError": "kaji.runtime.agents.context",
    "ContextWindow": "kaji.runtime.agents.context",
    "ContextWindowOverflowError": "kaji.runtime.agents.context",
    "EffectiveRuntimeLimits": "kaji.runtime.agents.runtime",
    "EventApprovalHandler": "kaji.runtime.agents.approval",
    "EventBackedApprovalHandler": "kaji.runtime.agents.approval",
    "HistoryStore": "kaji.runtime.agents.history",
    "InMemoryHistoryStore": "kaji.runtime.agents.history",
    "InMemoryTurnCoordinator": "kaji.runtime.agents.coordinator",
    "JournalEventEmitter": "kaji.runtime.agents.planner",
    "MissingToolIdentityError": "kaji.runtime.agents.context",
    "ProviderCancellationContractViolation": "kaji.runtime.agents.limits",
    "StreamDiagnostics": "kaji.runtime.agents.stream",
    "ToolExecutionContext": "kaji.runtime.agents.context",
    "ToolInvocation": "kaji.runtime.agents.context",
    "ToolPlanner": "kaji.runtime.agents.planner",
    "TurnContext": "kaji.runtime.agents.context",
    "TurnCoordinator": "kaji.runtime.agents.coordinator",
    "TurnExecutionLimits": "kaji.runtime.agents.limits",
    "TurnResult": "kaji.runtime.agents.runtime",
    "TurnTimeoutError": "kaji.runtime.agents.limits",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target), name)


def __dir__() -> list[str]:
    return sorted(__all__)
