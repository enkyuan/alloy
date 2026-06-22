"""Pin the agentkit top-level public surface so additions are deliberate."""

from __future__ import annotations

import agentkit


EXPECTED_PUBLIC = {
    "AgentBuilder",
    "AgentRuntime",
    "CancellationToken",
    "EventBus",
    "EventStore",
    "InMemoryEventBus",
    "InMemoryEventStore",
    "UserMessage",
    "FunctionTool",
    "Integration",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "RegisterTool",
    "ListToolSpecs",
    "ModelProvider",
    "GetProvider",
    "RegisterProvider",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAPIError",
    "ReplaySession",
    "RequestPaymentTool",
    "SessionManager",
    "SessionState",
    "ToolSpec",
}


def test_public_surface_is_pinned() -> None:
    public = {
        n for n in dir(agentkit) if not n.startswith("_") and n != "TYPE_CHECKING"
    }
    # __version__ is the only non-LAZY exported name.
    public -= {"__version__"}
    assert public == EXPECTED_PUBLIC, sorted(public ^ EXPECTED_PUBLIC)


def test_each_public_name_resolves() -> None:
    for name in EXPECTED_PUBLIC:
        getattr(agentkit, name)  # raises if the lazy module is broken


def test_internal_names_still_importable_from_subpackages() -> None:
    # Things removed from the top-level lazy map must still be importable
    # from their canonical subpackage.
    from agentkit.runtime.agents import AgentStrategy
    from agentkit.runtime.agents.planner import ToolPlanner, ToolExecutor
    from agentkit.runtime.sessions.store import (
        InMemorySessionStore,
        SessionStore,
        SessionRecord,
    )
    from agentkit.runtime.tools.registry import (
        ExecuteTool,
        ClearTools,
        ToolSpecFromModel,
    )
    from agentkit.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
    from agentkit.runtime.integrations import BoundTool

    # Trivial assertions just to suppress unused-import linters and prove the
    # imports executed.
    assert callable(ToolPlanner) or ToolPlanner is not None
    assert SessionStore is not None
    assert ToolPolicy is not None
    assert BoundTool is not None
