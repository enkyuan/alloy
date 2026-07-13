"""AgentReasoningNode runs end-to-end with no infra (#9).

The default history store is in-memory; we inject MockProvider directly so the
node's full generate() flow runs without Redis, a DB, or a network call.
"""

from unittest.mock import patch

import pytest

from kaji_serve.runtime.nodes.agentic import AgentReasoningNode
from kaji_serve.runtime.messaging.bus import Message
from kaji.runtime.tools.registry import ToolSpec, _TOOL_SPECS
from kaji.modalities.voice.event_models import (
    AgentResponse,
    ToolResult,
    UserTranscriptionReceived,
)
from tests.helpers.mock_provider import MockProvider


def _message(content, user_id="u1"):
    return Message(
        source="test",
        event=UserTranscriptionReceived(content=content, user_id=user_id),
    )


@pytest.fixture
def use_mock_provider():
    with patch(
        "kaji_serve.runtime.nodes.agentic.get_provider",
        return_value=MockProvider(),
    ):
        yield


@pytest.fixture
def registered_tool():
    spec = ToolSpec(
        name="ping",
        description="Ping a host.",
        parameters={"type": "object", "properties": {}, "required": []},
        risk="read",
    )
    _TOOL_SPECS[spec.name] = spec
    try:
        yield spec
    finally:
        _TOOL_SPECS.pop(spec.name, None)


@pytest.mark.asyncio
async def test_node_text_response_no_tools(use_mock_provider):
    """With no tools registered, the node returns a plain text response."""
    # Guard: ensure no tools leak in from other tests.
    with patch("kaji_serve.runtime.nodes.agentic.build_tools_payload", return_value=[]):
        node = AgentReasoningNode(system_prompt="You are helpful.")
        outputs = [chunk async for chunk in node.generate(_message("hello"))]

    responses = [o for o in outputs if isinstance(o, AgentResponse)]
    assert len(responses) == 1
    assert responses[0].content == "mock response"
    # History persisted in-memory: user turn + assistant reply.
    history = await node._history.get("u1")
    assert [m["role"] for m in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_node_tool_loop_no_infra(use_mock_provider, registered_tool):
    """The scatter-gather tool loop runs end-to-end with the in-memory store."""
    executed = []

    async def fake_execute_tool(user_id, name, args, db=None):
        executed.append(name)
        return {"status": "ok"}

    with (
        patch(
            "kaji_serve.runtime.nodes.agentic.execute_tool",
            side_effect=fake_execute_tool,
        ),
        patch(
            "kaji.runtime.tools.retriever.ToolRetriever.get_top_tools",
            return_value=["ping"],
        ),
    ):
        node = AgentReasoningNode(system_prompt="You are helpful.")
        outputs = [chunk async for chunk in node.generate(_message("ping it"))]

    # The tool was executed (the mock keeps requesting it since this node records
    # results as `assistant` summaries, so the loop runs up to MAX_TOOL_ITERATIONS
    # before forcing a final response — bounded, no infra involved).
    assert executed and all(name == "ping" for name in executed)
    assert any(isinstance(o, ToolResult) for o in outputs)
    assert any(isinstance(o, AgentResponse) for o in outputs)
    # Conversation history was tracked in-memory throughout.
    assert len(await node._history.get("u1")) > 0


@pytest.mark.asyncio
async def test_node_missing_user_id_yields_nothing(use_mock_provider):
    node = AgentReasoningNode(system_prompt="x")
    msg = Message(source="test", event=UserTranscriptionReceived(content="hi"))
    assert [chunk async for chunk in node.generate(msg)] == []
