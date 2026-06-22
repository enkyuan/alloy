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
    # from their canonical subpackage. Each name is asserted to silence
    # F401 (unused-import) and prove the import resolved.
    from agentkit.runtime.agents import AgentStrategy
    from agentkit.runtime.agents.planner import ToolExecutor, ToolPlanner
    from agentkit.runtime.integrations import BoundTool
    from agentkit.runtime.sessions.store import (
        InMemorySessionStore,
        SessionRecord,
        SessionStore,
    )
    from agentkit.runtime.tools.policies import ToolPolicy, ToolPolicyViolation
    from agentkit.runtime.tools.registry import (
        ClearTools,
        ExecuteTool,
        ToolSpecFromModel,
    )

    for obj in (
        AgentStrategy,
        ToolPlanner,
        ToolExecutor,
        InMemorySessionStore,
        SessionStore,
        SessionRecord,
        ExecuteTool,
        ClearTools,
        ToolSpecFromModel,
        ToolPolicy,
        ToolPolicyViolation,
        BoundTool,
    ):
        assert obj is not None
