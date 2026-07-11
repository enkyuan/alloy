"""Focused coverage for public effective-limit diagnostics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from kaji import EffectiveRuntimeLimits
from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.context import ContextWindow
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.tools.execution import ToolExecutionController, ToolExecutionLimits
from tests.helpers.mock_provider import MockProvider


@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        (0, ValueError),
        (-1, ValueError),
        (True, TypeError),
        (1.5, TypeError),
        (float("nan"), TypeError),
        (float("inf"), TypeError),
        (float("-inf"), TypeError),
    ],
)
def test_agent_strategy_rejects_invalid_max_iterations(
    value: Any, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type, match="max_iterations must be a positive integer"):
        AgentStrategy(max_iterations=value)


def test_agent_strategy_cannot_drift_after_runtime_construction() -> None:
    strategy = AgentStrategy(max_iterations=2)
    runtime = AgentRuntime(
        bus=InMemoryEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        strategy=strategy,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(strategy, "max_iterations", 9)

    assert runtime.effective_limits().max_tool_iterations == 2


def test_effective_limits_report_beta_defaults_as_an_immutable_public_type() -> None:
    runtime = AgentRuntime(
        bus=InMemoryEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
    )

    limits = runtime.effective_limits()

    assert limits == EffectiveRuntimeLimits(
        max_tool_iterations=5,
        context_window_turns=32,
        context_window_characters=100_000,
        tool_max_parallel=4,
        tool_timeout_seconds=30.0,
        approval_timeout_seconds=300.0,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(limits, "max_tool_iterations", 1)


def test_effective_limits_report_builder_overrides() -> None:
    runtime = (
        AgentBuilder()
        .provider(MockProvider())
        .strategy(AgentStrategy(max_iterations=2))
        .context_window(ContextWindow(max_turns=7, max_characters=1_234))
        .tool_execution_limits(
            ToolExecutionLimits(
                max_parallel=3,
                timeout_seconds=1.5,
                approval_timeout_seconds=2.5,
            )
        )
        .build()
    )

    assert runtime.effective_limits() == EffectiveRuntimeLimits(
        max_tool_iterations=2,
        context_window_turns=7,
        context_window_characters=1_234,
        tool_max_parallel=3,
        tool_timeout_seconds=1.5,
        approval_timeout_seconds=2.5,
    )


def test_effective_limits_use_an_explicit_planners_controller() -> None:
    async def executor(_invocation: object) -> dict[str, object]:
        return {}

    controller = ToolExecutionController(
        limits=ToolExecutionLimits(
            max_parallel=2,
            timeout_seconds=4.0,
            approval_timeout_seconds=6.0,
        )
    )
    planner = ToolPlanner(executor=executor, controller=controller)
    runtime = AgentRuntime(
        bus=InMemoryEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        planner=planner,
        strategy=AgentStrategy(max_iterations=3),
        context_window=ContextWindow(max_turns=None, max_characters=9_999),
    )

    assert runtime.effective_limits() == EffectiveRuntimeLimits(
        max_tool_iterations=3,
        context_window_turns=None,
        context_window_characters=9_999,
        tool_max_parallel=2,
        tool_timeout_seconds=4.0,
        approval_timeout_seconds=6.0,
    )
