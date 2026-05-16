import asyncio
from typing import Any, AsyncGenerator, Dict, List

import pytest

from src.agents.cancellation import CancellationToken
from src.agents.planner import ToolPlanner
from src.agents.runtime import AgentRuntime
from src.agents.strategy import AgentStrategy
from src.events.bus import EventBus
from src.events.schemas import AgentKitEvent, CancellationRequested, UserMessage
from src.events.store import InMemoryEventStore
from src.events.types import EventType
from src.providers.base import ModelProvider
from src.providers.types import GenerateResponse, ModelResponseChunk


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
