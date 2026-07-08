"""Unit tests for ToolPlanner — policy, approval, and scatter-gather."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from kaji.infra.events.schemas import KajiEvent
from kaji.infra.events.types import EventType
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.tools.policies import ToolPolicy
from kaji.runtime.tools.registry import ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect(
    planner: ToolPlanner,
    session_id: str,
    calls: List[Dict[str, Any]],
) -> tuple[List[KajiEvent], List[Dict[str, Any]]]:
    emitted: List[KajiEvent] = []

    async def emit(event: KajiEvent) -> None:
        emitted.append(event)

    results = await planner.execute_scatter_gather(session_id, calls, emit)
    return emitted, results


def _types(events: List[KajiEvent]) -> List[str]:
    return [e.type for e in events]


# ---------------------------------------------------------------------------
# Basic lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_emits_lifecycle_on_success():
    executor = AsyncMock(return_value={"ok": True})
    planner = ToolPlanner(executor=executor)

    emitted, results = await _collect(
        planner, "sess-1", [{"id": "c1", "name": "search", "arguments": {"q": "x"}}]
    )

    assert _types(emitted) == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
    ]
    assert results[0]["result"] == {"ok": True}


@pytest.mark.asyncio
async def test_planner_emits_failed_on_executor_error():
    executor = AsyncMock(side_effect=RuntimeError("boom"))
    planner = ToolPlanner(executor=executor)

    emitted, results = await _collect(
        planner, "sess-1", [{"id": "c2", "name": "bad", "arguments": {}}]
    )

    assert EventType.TOOL_CALL_FAILED in _types(emitted)
    assert "error" in results[0]
    assert "boom" in results[0]["error"]


@pytest.mark.parametrize("bad_args", [[], "not-object", None])
@pytest.mark.asyncio
async def test_planner_rejects_non_object_arguments_before_executor(bad_args):
    executor = AsyncMock(return_value={"ok": True})
    planner = ToolPlanner(executor=executor)

    emitted, results = await _collect(
        planner, "sess-bad-args", [{"id": "bad-args", "name": "search", "arguments": bad_args}]
    )

    executor.assert_not_called()
    assert _types(emitted) == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert "Invalid tool arguments" in results[0]["error"]
    assert "arguments must be an object" in results[0]["error"]


@pytest.mark.asyncio
async def test_planner_generates_call_id_when_absent():
    executor = AsyncMock(return_value={})
    planner = ToolPlanner(executor=executor)

    emitted, _ = await _collect(
        planner, "sess-1", [{"name": "search", "arguments": {}}]
    )

    started = next(e for e in emitted if e.type == EventType.TOOL_CALL_STARTED)
    assert started.tool_call_id


@pytest.mark.asyncio
async def test_planner_includes_catalog_name_metadata_when_available():
    executor = AsyncMock(return_value={"ok": True})
    specs = {
        "weather_get_weather": ToolSpec(
            name="weather_get_weather",
            catalog_name="weather.get_weather",
            description="d",
            parameters={},
        )
    }
    planner = ToolPlanner(executor=executor, specs=specs)

    emitted, _ = await _collect(
        planner,
        "sess-catalog",
        [{"id": "cat1", "name": "weather_get_weather", "arguments": {}}],
    )

    assert all(e.metadata == {"catalog_name": "weather.get_weather"} for e in emitted)


# ---------------------------------------------------------------------------
# Allow / deny policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_deny_blocks_before_started():
    executor = AsyncMock(return_value={})
    planner = ToolPlanner(executor=executor, policy=ToolPolicy(denied={"blocked"}))

    emitted, results = await _collect(
        planner, "sess-deny", [{"id": "d1", "name": "blocked", "arguments": {}}]
    )

    executor.assert_not_called()
    assert _types(emitted) == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert "not permitted" in results[0]["error"].lower()


@pytest.mark.asyncio
async def test_planner_allow_list_permits_listed_tool():
    executor = AsyncMock(return_value={"x": 1})
    planner = ToolPlanner(
        executor=executor, policy=ToolPolicy(allowed={"allowed_tool"})
    )

    emitted, _ = await _collect(
        planner, "sess-allow", [{"id": "a1", "name": "allowed_tool", "arguments": {}}]
    )

    executor.assert_called_once()
    assert EventType.TOOL_CALL_COMPLETED in _types(emitted)


@pytest.mark.asyncio
async def test_planner_allow_list_accepts_catalog_name_alias():
    executor = AsyncMock(return_value={"x": 1})
    specs = {
        "weather_get_weather": ToolSpec(
            name="weather_get_weather",
            catalog_name="weather.get_weather",
            description="d",
            parameters={},
        )
    }
    planner = ToolPlanner(
        executor=executor,
        policy=ToolPolicy(allowed={"weather.get_weather"}),
        specs=specs,
    )

    emitted, _ = await _collect(
        planner,
        "sess-allow-catalog",
        [{"id": "ac1", "name": "weather_get_weather", "arguments": {}}],
    )

    executor.assert_called_once()
    assert EventType.TOOL_CALL_COMPLETED in _types(emitted)


@pytest.mark.asyncio
async def test_planner_deny_list_blocks_catalog_name_alias():
    executor = AsyncMock(return_value={})
    specs = {
        "weather_get_weather": ToolSpec(
            name="weather_get_weather",
            catalog_name="weather.get_weather",
            description="d",
            parameters={},
        )
    }
    planner = ToolPlanner(
        executor=executor,
        policy=ToolPolicy(denied={"weather.get_weather"}),
        specs=specs,
    )

    emitted, results = await _collect(
        planner,
        "sess-deny-catalog",
        [{"id": "dc1", "name": "weather_get_weather", "arguments": {}}],
    )

    executor.assert_not_called()
    assert _types(emitted) == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_FAILED,
    ]
    assert "not permitted" in results[0]["error"].lower()


@pytest.mark.asyncio
async def test_planner_allow_list_blocks_unlisted_tool():
    executor = AsyncMock(return_value={})
    planner = ToolPlanner(executor=executor, policy=ToolPolicy(allowed={"search"}))

    emitted, results = await _collect(
        planner,
        "sess-allow-block",
        [{"id": "ab1", "name": "other_tool", "arguments": {}}],
    )

    executor.assert_not_called()
    assert EventType.TOOL_CALL_FAILED in _types(emitted)
    assert "not permitted" in results[0]["error"].lower()


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_approval_approved_proceeds():
    executor = AsyncMock(return_value={"done": True})
    specs = {
        "nuke": ToolSpec(
            name="nuke", description="d", parameters={}, risk="destructive"
        )
    }
    policy = ToolPolicy(require_approval_for={"destructive"})
    approval_handler = AsyncMock(return_value=True)
    planner = ToolPlanner(
        executor=executor, policy=policy, approval_handler=approval_handler, specs=specs
    )

    emitted, results = await _collect(
        planner, "sess-approved", [{"id": "ap1", "name": "nuke", "arguments": {}}]
    )

    types = _types(emitted)
    assert EventType.TOOL_APPROVAL_REQUESTED in types
    assert EventType.TOOL_APPROVAL_APPROVED in types
    assert EventType.TOOL_CALL_COMPLETED in types
    assert results[0]["result"] == {"done": True}


@pytest.mark.asyncio
async def test_planner_approval_rejected_skips_execution():
    executor = AsyncMock(return_value={})
    specs = {
        "charge": ToolSpec(
            name="charge", description="d", parameters={}, risk="financial"
        )
    }
    policy = ToolPolicy(require_approval_for={"financial"})
    approval_handler = AsyncMock(return_value=False)
    planner = ToolPlanner(
        executor=executor, policy=policy, approval_handler=approval_handler, specs=specs
    )

    emitted, results = await _collect(
        planner, "sess-rejected", [{"id": "rj1", "name": "charge", "arguments": {}}]
    )

    executor.assert_not_called()
    types = _types(emitted)
    assert EventType.TOOL_APPROVAL_REJECTED in types
    # TOOL_CALL_FAILED must follow so replay projects the outcome into history,
    # preventing the agent from re-requesting the same tool until max_iterations.
    assert EventType.TOOL_CALL_FAILED in types
    assert EventType.TOOL_CALL_STARTED not in types
    assert "error" in results[0]


@pytest.mark.asyncio
async def test_planner_no_approval_handler_rejects_by_default():
    executor = AsyncMock(return_value={})
    specs = {
        "add_user": ToolSpec(
            name="add_user", description="d", parameters={}, risk="admin"
        )
    }
    policy = ToolPolicy(require_approval_for={"admin"})
    planner = ToolPlanner(executor=executor, policy=policy, specs=specs)

    emitted, results = await _collect(
        planner, "sess-no-handler", [{"id": "nh1", "name": "add_user", "arguments": {}}]
    )

    executor.assert_not_called()
    types = _types(emitted)
    assert EventType.TOOL_APPROVAL_REJECTED in types
    assert EventType.TOOL_CALL_FAILED in types
    assert "error" in results[0]


@pytest.mark.asyncio
async def test_planner_low_risk_tool_skips_approval_gate():
    executor = AsyncMock(return_value={})
    specs = {
        "search": ToolSpec(name="search", description="d", parameters={}, risk="read")
    }
    policy = ToolPolicy(require_approval_for={"destructive"})
    planner = ToolPlanner(executor=executor, policy=policy, specs=specs)

    emitted, _ = await _collect(
        planner, "sess-low-risk", [{"id": "lr1", "name": "search", "arguments": {}}]
    )

    assert EventType.TOOL_APPROVAL_REQUESTED not in _types(emitted)
    assert EventType.TOOL_CALL_COMPLETED in _types(emitted)


# ---------------------------------------------------------------------------
# Scatter-gather concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_scatter_gather_runs_both_calls():
    call_log: list[str] = []

    async def executor(name: str, args: dict) -> dict:
        call_log.append(name)
        return {"name": name}

    planner = ToolPlanner(executor=executor)
    emitted, results = await _collect(
        planner,
        "sess-scatter",
        [
            {"id": "s1", "name": "tool_a", "arguments": {}},
            {"id": "s2", "name": "tool_b", "arguments": {}},
        ],
    )

    assert sorted(call_log) == ["tool_a", "tool_b"]
    assert len(results) == 2
    completed_types = [
        e.type for e in emitted if e.type == EventType.TOOL_CALL_COMPLETED
    ]
    assert len(completed_types) == 2
