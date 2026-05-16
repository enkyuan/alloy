import pytest

from sdk.agents.planner import ToolPlanner
from sdk.events.schemas import (
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRequested,
    ToolCallStarted,
)
from sdk.events.types import EventType


@pytest.mark.asyncio
async def test_tool_planner_emits_lifecycle_on_success():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(name: str, args: dict):
        return {"ok": True, "name": name, "args": args}

    planner = ToolPlanner(executor=executor)
    await planner.execute_scatter_gather(
        "sess-1",
        [{"id": "call-1", "name": "search", "arguments": {"q": "test"}}],
        emit,
    )

    types = [event.type for event in emitted]
    assert types == [
        EventType.TOOL_CALL_REQUESTED,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
    ]
    assert isinstance(emitted[0], ToolCallRequested)
    assert isinstance(emitted[-1], ToolCallCompleted)


@pytest.mark.asyncio
async def test_tool_planner_emits_failure_event():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def executor(_name: str, _args: dict):
        raise RuntimeError("tool exploded")

    planner = ToolPlanner(executor=executor)
    results = await planner.execute_scatter_gather(
        "sess-1",
        [{"id": "call-2", "name": "broken", "arguments": {}}],
        emit,
    )

    assert results[0]["error"] == "tool exploded"
    assert any(event.type == EventType.TOOL_CALL_FAILED for event in emitted)
    assert isinstance(
        next(event for event in emitted if event.type == EventType.TOOL_CALL_FAILED),
        ToolCallFailed,
    )


@pytest.mark.asyncio
async def test_tool_planner_generates_call_id_when_missing():
    emitted = []

    async def emit(event):
        emitted.append(event)

    async def _ok_executor(_name: str, _args: dict) -> str:
        return "ok"

    planner = ToolPlanner(executor=_ok_executor)
    await planner.execute_scatter_gather(
        "sess-1",
        [{"name": "search", "arguments": {}}],
        emit,
    )
    started = next(event for event in emitted if event.type == EventType.TOOL_CALL_STARTED)
    assert isinstance(started, ToolCallStarted)
    assert started.tool_call_id
