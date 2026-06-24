"""Pin the kaji top-level public surface so additions are deliberate."""

from __future__ import annotations

import kaji


# PEP 8 names: classes are CapWords, decorators / function helpers are
# snake_case. There are no UpperCamel aliases for decorators or helpers.
EXPECTED_PUBLIC = {
    "AgentBuilder",
    "AgentRuntime",
    "CancellationToken",
    "EventBus",
    "EventStore",
    "InMemoryEventBus",
    "InMemoryEventStore",
    "Integration",
    "ModelProvider",
    "ProviderAPIError",
    "ProviderConfigError",
    "ProviderError",
    "replay_session",
    "SessionManager",
    "SessionState",
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "UnknownToolError",
    "UserMessage",
    "function_tool",
    "get_provider",
    "list_tool_specs",
    "register_provider",
    "register_tool",
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
    # Things removed from the top-level lazy map must still be importable
    # from their canonical subpackage. Each name is asserted to silence
    # F401 (unused-import) and prove the import resolved.
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
