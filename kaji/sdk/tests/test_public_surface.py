"""Pin the kaji top-level public surface so additions are deliberate."""

from __future__ import annotations

import kaji


# PEP 8 names: classes are CapWords, decorators / function helpers are
# snake_case. There are no UpperCamel aliases for decorators or helpers.
EXPECTED_PUBLIC = {
    "AgentBuilder",
    "AgentRuntime",
    "ApprovalDecision",
    "ApprovalHandler",
    "ApprovalRequestContext",
    "AppendResult",
    "CancellationToken",
    "Chunk",
    "Clock",
    "Document",
    "DocumentRAG",
    "Embedder",
    "EmbeddingCache",
    "EventBus",
    "EventBufferOverflowError",
    "EventDeliveryError",
    "EventApprovalHandler",
    "EventBackedApprovalHandler",
    "EventIdConflictError",
    "EventJournal",
    "EventStore",
    "EventStoreCapacityError",
    "HistoryStore",
    "IdFactory",
    "InMemoryEventBus",
    "InMemoryEventJournal",
    "InMemoryEventStore",
    "InMemoryHistoryStore",
    "InMemorySessionStore",
    "InMemoryToolIdempotencyLedger",
    "InMemoryTurnCoordinator",
    "InMemoryVectorStore",
    "Integration",
    "JournalEventEmitter",
    "IdempotencyCapacityExceeded",
    "IdempotencyConflictError",
    "ModelProvider",
    "Measurement",
    "MetricsSink",
    "MissingToolIdentityError",
    "NewKajiEvent",
    "NOOP_METRICS",
    "NOOP_TRACE",
    "ProviderAPIError",
    "ProviderConfigError",
    "ProviderError",
    "replay_legacy_session",
    "replay_session",
    "SessionManager",
    "SessionRecord",
    "SessionState",
    "SessionStore",
    "SplitEventJournal",
    "StoredKajiEvent",
    "SystemClock",
    "SystemIdFactory",
    "SpanHandle",
    "ToolContext",
    "ToolExecutionController",
    "ToolExecutionContext",
    "ToolExecutionError",
    "ToolExecutionLimits",
    "ToolIdempotencyLedger",
    "ToolInvocation",
    "ToolArgumentValidationError",
    "ToolRegistry",
    "ToolRetriever",
    "ToolSchemaValidationError",
    "ToolSchemaValidator",
    "ToolSpec",
    "TurnCoordinator",
    "TurnContext",
    "TurnResult",
    "TraceSink",
    "UnknownToolError",
    "UnclassifiedToolRiskError",
    "UserMessage",
    "VectorStore",
    "build_tools_payload",
    "function_tool",
    "get_provider",
    "list_tool_specs",
    "register_provider",
    "register_tool",
    "spec_to_neutral",
    "to_anthropic",
    "to_gemini",
    "to_openai",
    "tool",
}


def test_public_surface_is_pinned() -> None:
    public = {n for n in dir(kaji) if not n.startswith("_") and n != "TYPE_CHECKING"}
    # __version__ is the only non-LAZY exported name.
    public -= {"__version__"}
    assert public == EXPECTED_PUBLIC, sorted(public ^ EXPECTED_PUBLIC)


def test_each_public_name_resolves() -> None:
    for name in EXPECTED_PUBLIC:
        getattr(kaji, name)  # raises if the lazy module is broken


def test_internal_names_still_importable_from_subpackages() -> None:
    # Names not in the top-level lazy map (and names that ARE in the top-level
    # map but whose canonical home is a subpackage) must remain importable
    # from their submodule path. Each name is asserted to silence F401 and
    # prove the import resolved.
    from kaji.runtime.agents import AgentStrategy
    from kaji.runtime.agents.planner import ToolExecutor, ToolPlanner
    from kaji.runtime.integrations import BoundTool
    from kaji.runtime.sessions.store import (
        InMemorySessionStore,
        SessionRecord,
        SessionStore,
    )
    from kaji.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
    from kaji.runtime.tools.registry import (
        clear_tools,
        execute_tool,
        tool_spec_from_model,
    )

    for obj in (
        AgentStrategy,
        ToolPlanner,
        ToolExecutor,
        InMemorySessionStore,
        SessionStore,
        SessionRecord,
        execute_tool,
        clear_tools,
        tool_spec_from_model,
        ToolPolicy,
        ToolPolicyViolation,
        BoundTool,
    ):
        assert obj is not None
