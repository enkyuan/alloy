"""Focused coverage for public effective-limit diagnostics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from kaji import EffectiveRuntimeLimits
from kaji.infra.events.store import InMemoryEventStore
from kaji.runtime.agents.builder import AgentBuilder
from kaji.runtime.agents.context import ContextWindow
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.limits import TurnExecutionLimits, TurnTimeoutError
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
        bus=None,
        store=InMemoryEventStore(),
        provider=MockProvider(),
        strategy=strategy,
    )

    with pytest.raises(FrozenInstanceError):
        setattr(strategy, "max_iterations", 9)

    assert runtime.effective_limits().max_tool_iterations == 2


def test_effective_limits_report_beta_defaults_as_an_immutable_public_type() -> None:
    runtime = AgentRuntime(
        bus=None,
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
        turn_timeout_seconds=120.0,
        provider_cancellation_grace_seconds=5.0,
        provider_text_max_bytes=262_144,
        provider_tool_arguments_max_bytes=65_536,
        provider_response_max_bytes=524_288,
        provider_tool_calls_max=64,
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
        .turn_execution_limits(
            TurnExecutionLimits(
                timeout_seconds=12.5,
                provider_cancellation_grace_seconds=0.25,
                provider_text_max_bytes=1_024,
                provider_tool_arguments_max_bytes=512,
                provider_response_max_bytes=2_048,
                provider_tool_calls_max=3,
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
        turn_timeout_seconds=12.5,
        provider_cancellation_grace_seconds=0.25,
        provider_text_max_bytes=1_024,
        provider_tool_arguments_max_bytes=512,
        provider_response_max_bytes=2_048,
        provider_tool_calls_max=3,
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
        bus=None,
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
        turn_timeout_seconds=120.0,
        provider_cancellation_grace_seconds=5.0,
        provider_text_max_bytes=262_144,
        provider_tool_arguments_max_bytes=65_536,
        provider_response_max_bytes=524_288,
        provider_tool_calls_max=64,
    )


def test_turn_timeout_error_carries_phase_specific_semantics() -> None:
    error = TurnTimeoutError(phase="tool", retryable=False, outcome="unknown")

    assert error.code == "TURN_TIMEOUT"
    assert error.phase == "tool"
    assert error.retryable is False
    assert error.outcome == "unknown"
    assert str(error) == "Turn deadline exceeded during tool"


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"timeout_seconds": True}, TypeError),
        ({"timeout_seconds": 0}, ValueError),
        ({"timeout_seconds": float("nan")}, ValueError),
        ({"provider_cancellation_grace_seconds": float("inf")}, ValueError),
        ({"provider_text_max_bytes": True}, TypeError),
        ({"provider_tool_calls_max": 0}, ValueError),
    ],
)
def test_turn_execution_limits_reject_invalid_values(
    kwargs: dict[str, Any], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        TurnExecutionLimits(**kwargs)


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"phase": "invalid", "retryable": True, "outcome": "not_started"}, ValueError),
        ({"phase": "queue", "retryable": 1, "outcome": "not_started"}, TypeError),
        ({"phase": "queue", "retryable": True, "outcome": "invalid"}, ValueError),
    ],
)
def test_turn_timeout_error_rejects_invalid_semantics(
    kwargs: dict[str, Any], error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        TurnTimeoutError(**kwargs)
