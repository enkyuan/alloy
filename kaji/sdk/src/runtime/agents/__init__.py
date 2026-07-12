"""Agent runtime: the provider-agnostic ReAct loop and its building blocks."""

from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.approval import (
    ApprovalDecision,
    ApprovalHandler,
    ApprovalRequestContext,
    EventApprovalHandler,
    EventBackedApprovalHandler,
)
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.coordinator import InMemoryTurnCoordinator, TurnCoordinator
from kaji.runtime.agents.limits import (
    ProviderCancellationContractViolation,
    TurnExecutionLimits,
    TurnTimeoutError,
)
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
from kaji.runtime.agents.planner import JournalEventEmitter, ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime, EffectiveRuntimeLimits, TurnResult
from kaji.runtime.agents.strategy import AgentStrategy

__all__ = [
    "AgentBuilder",
    "AgentRuntime",
    "AgentStrategy",
    "ApprovalDecision",
    "ApprovalHandler",
    "ApprovalRequestContext",
    "CancellationToken",
    "ContextDiagnostics",
    "ContextIntegrityError",
    "ContextWindow",
    "ContextWindowOverflowError",
    "EffectiveRuntimeLimits",
    "HistoryStore",
    "EventApprovalHandler",
    "EventBackedApprovalHandler",
    "InMemoryTurnCoordinator",
    "InMemoryHistoryStore",
    "JournalEventEmitter",
    "MissingToolIdentityError",
    "ToolExecutionContext",
    "ToolInvocation",
    "ToolPlanner",
    "TurnCoordinator",
    "TurnExecutionLimits",
    "TurnTimeoutError",
    "ProviderCancellationContractViolation",
    "TurnResult",
    "TurnContext",
]
