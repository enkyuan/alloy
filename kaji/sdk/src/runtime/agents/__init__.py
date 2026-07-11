"""Agent runtime: the provider-agnostic ReAct loop and its building blocks."""

from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.coordinator import InMemoryTurnCoordinator, TurnCoordinator
from kaji.runtime.agents.context import (
    ContextDiagnostics,
    ContextIntegrityError,
    ContextWindow,
    ContextWindowOverflowError,
    MissingToolIdentityError,
    ToolExecutionContext,
    ToolInvocation,
    TurnContext,
)
from kaji.runtime.agents.history import HistoryStore, InMemoryHistoryStore
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime, TurnResult
from kaji.runtime.agents.strategy import AgentStrategy

__all__ = [
    "AgentBuilder",
    "AgentRuntime",
    "AgentStrategy",
    "CancellationToken",
    "ContextDiagnostics",
    "ContextIntegrityError",
    "ContextWindow",
    "ContextWindowOverflowError",
    "HistoryStore",
    "InMemoryTurnCoordinator",
    "InMemoryHistoryStore",
    "MissingToolIdentityError",
    "ToolExecutionContext",
    "ToolInvocation",
    "ToolPlanner",
    "TurnCoordinator",
    "TurnResult",
    "TurnContext",
]
