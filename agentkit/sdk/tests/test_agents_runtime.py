import asyncio
from typing import Any, AsyncGenerator, Dict, List

import pytest

from agentkit.runtime.agents.cancellation import CancellationToken
from agentkit.runtime.agents.planner import ToolPlanner
from agentkit.runtime.agents.runtime import AgentRuntime
from agentkit.infra.events.bus import EventBus
from agentkit.infra.events.schemas import (
    AgentKitEvent,
    UserMessage,
)
from agentkit.infra.events.store import InMemoryEventStore
from agentkit.infra.events.types import EventType
from agentkit.runtime.providers.base import ModelProvider
from agentkit.runtime.providers.types import GenerateResponse, ModelResponseChunk
from agentkit.runtime.tools.registry import ToolSpec
from tests.helpers.mock_provider import MockProvider as _RegistryMockProvider


class MockEventBus(EventBus):
    def __init__(self):
        self.published = []

    async def publish(self, event: AgentKitEvent) -> str:
        self.published.append(event)
        return "mock-id"


class MockProvider(ModelProvider):
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: Dict[str, Any] | None = None,
        cancellation_token: Any | None = None,
    ) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        cancellation_token: Any | None = None,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        yield ModelResponseChunk(delta="Hello", tool_calls=[])
        yield ModelResponseChunk(delta=" World!", tool_calls=[])


async def mock_executor(name: str, args: Dict[str, Any]) -> Any:
    return "success"


@pytest.mark.asyncio
async def test_agent_runtime_basic_turn():
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)
    provider = MockProvider()

    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)

    # Simulate a user message
    await store.append(UserMessage(session_id="test-1", content="Hi"))

    # Run a single turn
    await runtime.run_turn("test-1")

    # Check that events were emitted
    events = await store.get_events("test-1")
    types = [e.type for e in events]

    assert EventType.USER_MESSAGE in types
    assert EventType.AGENT_REASONING_STARTED in types
    assert EventType.AGENT_MESSAGE_DELTA in types
    assert EventType.AGENT_MESSAGE_COMPLETED in types

    completed_events = [
        e for e in events if e.type == EventType.AGENT_MESSAGE_COMPLETED
    ]
    assert len(completed_events) == 1
    assert completed_events[0].content == "Hello World!"


@pytest.mark.asyncio
async def test_agent_runtime_tool_loop_end_to_end():
    """A full request -> execute -> continue loop using MockProvider.

    Exercises the tool path: MockProvider requests the first offered tool,
    the planner executes it, and the loop re-reads state (now containing the
    tool result) and finishes with a plain text response.
    """
    store = InMemoryEventStore()
    bus = MockEventBus()

    executed: List[str] = []

    async def executor(name: str, args: Dict[str, Any]) -> Any:
        executed.append(name)
        return {"ok": True}

    planner = ToolPlanner(executor=executor)
    provider = _RegistryMockProvider()

    tools = [
        ToolSpec(
            name="lookup",
            description="Look something up.",
            parameters={"type": "object", "properties": {}, "required": []},
        )
    ]

    runtime = AgentRuntime(
        bus=bus, store=store, provider=provider, planner=planner, tools=tools
    )

    await store.append(UserMessage(session_id="tool-1", content="Use a tool"))
    await runtime.run_turn("tool-1")

    events = await store.get_events("tool-1")
    types = [e.type for e in events]

    # The tool was actually executed exactly once...
    assert executed == ["lookup"]
    # ...with the full lifecycle emitted by the planner...
    assert EventType.TOOL_CALL_REQUESTED in types
    assert EventType.TOOL_CALL_STARTED in types
    assert EventType.TOOL_CALL_COMPLETED in types
    # ...and the loop continued past the tool to a final text message.
    completed = [e for e in events if e.type == EventType.AGENT_MESSAGE_COMPLETED]
    assert len(completed) == 1
    assert completed[0].content == "mock"


@pytest.mark.asyncio
async def test_agent_runtime_no_tools_runs_clean():
    """With no tools configured the loop still runs a plain text turn."""
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)
    provider = _RegistryMockProvider()

    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)

    await store.append(UserMessage(session_id="notools-1", content="Hi"))
    await runtime.run_turn("notools-1")

    events = await store.get_events("notools-1")
    types = [e.type for e in events]

    assert EventType.TOOL_CALL_REQUESTED not in types
    completed = [e for e in events if e.type == EventType.AGENT_MESSAGE_COMPLETED]
    assert len(completed) == 1
    assert completed[0].content == "mock"


@pytest.mark.asyncio
async def test_get_provider_mock_is_public_zero_setup_provider():
    """The mock provider is public so quickstarts and tests run with no API key."""
    from agentkit.runtime.providers import get_provider
    from agentkit.runtime.providers.mock import MockProvider

    assert isinstance(get_provider("mock"), MockProvider)


@pytest.mark.asyncio
async def test_agent_runtime_cancellation():
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)

    class SlowMockProvider(ModelProvider):
        async def generate(
            self,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]] | None = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            response_format: Dict[str, Any] | None = None,
            cancellation_token: Any | None = None,
        ) -> GenerateResponse:
            return GenerateResponse(text="")

        async def generate_stream(
            self,
            messages: List[Dict[str, Any]],
            tools: List[Dict[str, Any]] | None = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            yield ModelResponseChunk(delta="Start")
            await asyncio.sleep(0.1)  # Simulate slow generation
            yield ModelResponseChunk(delta="Finish")

    provider = SlowMockProvider()
    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)

    token = CancellationToken()

    # Start the turn in the background
    turn_task = asyncio.create_task(
        runtime.run_turn("test-2", cancellation_token=token)
    )

    # Wait a bit, then cancel
    await asyncio.sleep(0.05)
    token.cancel()

    await turn_task

    events = await store.get_events("test-2")
    types = [e.type for e in events]

    # It should have started, yielded the first chunk, then cancelled before "Finish"
    assert EventType.AGENT_REASONING_STARTED in types
    assert EventType.CANCELLATION_COMPLETED in types

    # AgentMessageCompleted should NOT be there because it was interrupted
    assert EventType.AGENT_MESSAGE_COMPLETED not in types


@pytest.mark.asyncio
async def test_agent_runtime_send_publishes_user_message_to_bus():
    """send() must emit UserMessage via _emit (store + bus), not store-only."""
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)
    provider = MockProvider()

    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)
    await runtime.send("s1", "hello via send")

    events = await store.get_events("s1")
    types = [e.type for e in events]

    # UserMessage must be in the store
    assert EventType.USER_MESSAGE in types
    # UserMessage must also have been published to the bus
    bus_types = [e.type for e in bus.published]
    assert EventType.USER_MESSAGE in bus_types
    # Agent turn ran and completed
    assert EventType.AGENT_MESSAGE_COMPLETED in types


@pytest.mark.asyncio
async def test_tool_call_id_preserved_in_replay_and_second_turn_messages():
    """ReplaySession must include tool_call_id on tool messages.

    This is the regression test for the multi-turn tool loop bug: without
    tool_call_id the second provider request is structurally broken for
    OpenAI/Anthropic (they require matching IDs on tool results).
    """
    from agentkit.infra.events.replay import ReplaySession
    from agentkit.infra.events.schemas import (
        ToolCallCompleted,
        ToolCallFailed,
        ToolCallRequested,
        ToolCallStarted,
        UserMessage,
    )
    from agentkit.infra.events.store import InMemoryEventStore

    store = InMemoryEventStore()
    session_id = "s-replay-id"

    await store.append(UserMessage(session_id=session_id, content="do something"))
    await store.append(
        ToolCallRequested(
            session_id=session_id,
            tool_name="lookup",
            tool_args={"q": "test"},
            tool_call_id="call-abc",
        )
    )
    await store.append(
        ToolCallStarted(session_id=session_id, tool_name="lookup", tool_call_id="call-abc")
    )
    await store.append(
        ToolCallCompleted(
            session_id=session_id,
            tool_name="lookup",
            tool_call_id="call-abc",
            result={"answer": 42},
        )
    )

    events = await store.get_events(session_id)
    state = ReplaySession(events)

    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call-abc", (
        "tool_call_id must be preserved in replay so providers can correlate results"
    )


@pytest.mark.asyncio
async def test_tool_call_id_preserved_on_failed_tool_replay():
    """TOOL_CALL_FAILED events must also carry tool_call_id through replay."""
    from agentkit.infra.events.replay import ReplaySession
    from agentkit.infra.events.schemas import (
        ToolCallFailed,
        ToolCallRequested,
        UserMessage,
    )
    from agentkit.infra.events.store import InMemoryEventStore

    store = InMemoryEventStore()
    session_id = "s-replay-fail"

    await store.append(UserMessage(session_id=session_id, content="try something"))
    await store.append(
        ToolCallRequested(
            session_id=session_id,
            tool_name="risky",
            tool_args={},
            tool_call_id="call-xyz",
        )
    )
    await store.append(
        ToolCallFailed(
            session_id=session_id,
            tool_name="risky",
            tool_call_id="call-xyz",
            error="timeout",
        )
    )

    events = await store.get_events(session_id)
    state = ReplaySession(events)

    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call-xyz"
    assert "Error:" in tool_msgs[0]["content"]
