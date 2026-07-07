import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional

import pytest

from kaji.infra.events.bus import InMemoryEventBus
from kaji.infra.events.schemas import (
    KajiEvent,
    UserMessage,
)
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.providers.base import ModelProvider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    TokenMetrics,
)
from kaji.runtime.tools.registry import ToolSpec
from tests.helpers.mock_provider import MockProvider as _RegistryMockProvider


class MockEventBus(InMemoryEventBus):
    def __init__(self):
        self.published = []

    async def publish(self, event: KajiEvent) -> str:
        self.published.append(event)
        return "mock-id"


class MockProvider(ModelProvider):
    async def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
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
        tools: Optional[List[Dict[str, Any]]] = None,
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
async def test_agent_runtime_emits_streamed_usage_on_completed_message():
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)

    class TelemetryProvider(ModelProvider):
        async def generate(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
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
            tools: Optional[List[Dict[str, Any]]] = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            yield ModelResponseChunk(delta="hello")
            yield ModelResponseChunk(
                metrics=TokenMetrics(
                    prompt_tokens=3,
                    completion_tokens=2,
                    total_tokens=5,
                ),
                cost_usd=0.00001125,
            )

    runtime = AgentRuntime(
        bus=bus,
        store=store,
        provider=TelemetryProvider(),
        planner=planner,
    )

    await store.append(UserMessage(session_id="usage-1", content="Hi"))
    await runtime.run_turn("usage-1")

    events = await store.get_events("usage-1")
    completed = next(e for e in events if e.type == EventType.AGENT_MESSAGE_COMPLETED)

    assert completed.content == "hello"
    assert completed.tokens is not None
    assert completed.tokens.input == 3
    assert completed.tokens.output == 2
    assert completed.cost_usd == 0.00001125


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
async def test_agent_runtime_emits_exhausted_event_at_max_iterations():
    store = InMemoryEventStore()
    bus = MockEventBus()

    async def executor(name: str, args: Dict[str, Any]) -> Any:
        return {"ok": True}

    class AlwaysToolProvider(ModelProvider):
        async def generate(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
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
            tools: Optional[List[Dict[str, Any]]] = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            yield ModelResponseChunk(
                delta="",
                tool_calls=[{"id": "loop-1", "name": "lookup", "arguments": {}}],
            )

    runtime = AgentRuntime(
        bus=bus,
        store=store,
        provider=AlwaysToolProvider(),
        planner=ToolPlanner(executor=executor),
        tools=[
            ToolSpec(
                name="lookup",
                description="Look something up.",
                parameters={"type": "object", "properties": {}, "required": []},
            )
        ],
        strategy=AgentStrategy(max_iterations=2),
    )

    await store.append(UserMessage(session_id="exhaust-1", content="Use a tool"))
    await runtime.run_turn("exhaust-1")

    events = await store.get_events("exhaust-1")
    exhausted = [e for e in events if e.type == EventType.AGENT_TURN_EXHAUSTED]

    assert len(exhausted) == 1
    assert exhausted[0].max_iterations == 2
    assert exhausted[0].pending_tool_calls == [
        {"id": "loop-1", "name": "lookup", "arguments": {}}
    ]
    assert exhausted[0].reason == "max_iterations"


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
    from kaji.runtime.providers import get_provider
    from kaji.runtime.providers.mock import MockProvider

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
            tools: Optional[List[Dict[str, Any]]] = None,
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
            tools: Optional[List[Dict[str, Any]]] = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            yield ModelResponseChunk(delta="Start")
            await asyncio.sleep(0.1)  # Simulate slow generation
            if cancellation_token and getattr(
                cancellation_token, "is_cancelled", False
            ):
                raise asyncio.CancelledError()
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
async def test_agent_runtime_emits_cancellation_when_provider_raises_mid_stream():
    """When the provider raises asyncio.CancelledError mid-stream because the
    token was set, the runtime must catch it and emit CancellationCompleted so
    observers see the canonical terminal event. Without the try/except in
    run_turn the exception would escape and observers would never get notified.
    """
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)

    captured_token: Dict[str, Any] = {}

    class RaisingProvider(ModelProvider):
        async def generate(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
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
            tools: Optional[List[Dict[str, Any]]] = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            # The runtime must thread the token through; assert it did.
            assert cancellation_token is not None
            captured_token["t"] = cancellation_token
            yield ModelResponseChunk(delta="partial")
            # Mimic the real provider path: token flips during streaming,
            # the provider observes it on its next check, and raises.
            cancellation_token.cancel()
            raise asyncio.CancelledError()

    provider = RaisingProvider()
    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)

    await store.append(UserMessage(session_id="cancel-mid", content="go"))

    token = CancellationToken()
    # run_turn must not propagate CancelledError out.
    await runtime.run_turn("cancel-mid", cancellation_token=token)

    events = await store.get_events("cancel-mid")
    types = [e.type for e in events]

    assert EventType.AGENT_REASONING_STARTED in types
    assert EventType.AGENT_MESSAGE_DELTA in types  # partial chunk made it through
    assert EventType.CANCELLATION_COMPLETED in types
    assert EventType.AGENT_MESSAGE_COMPLETED not in types


@pytest.mark.asyncio
async def test_agent_runtime_reraises_when_cancel_is_external():
    """If CancelledError is raised but the runtime's own token is NOT set,
    the cancel came from outside (e.g. parent task cancellation). The
    runtime must re-raise so structured concurrency stays intact, rather
    than miscategorize the external cancel as a user-requested one.
    """
    store = InMemoryEventStore()
    bus = MockEventBus()
    planner = ToolPlanner(executor=mock_executor)

    class ExternallyCancelledProvider(ModelProvider):
        async def generate(
            self,
            messages: List[Dict[str, Any]],
            tools: Optional[List[Dict[str, Any]]] = None,
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
            tools: Optional[List[Dict[str, Any]]] = None,
            system_instruction: str | None = None,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            cancellation_token: Any | None = None,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            yield ModelResponseChunk(delta="x")
            # Simulate an external (parent-task) cancellation: CancelledError
            # raised but the runtime's own token was never set.
            raise asyncio.CancelledError()

    provider = ExternallyCancelledProvider()
    runtime = AgentRuntime(bus=bus, store=store, provider=provider, planner=planner)

    await store.append(UserMessage(session_id="ext-cancel", content="go"))

    token = CancellationToken()
    with pytest.raises(asyncio.CancelledError):
        await runtime.run_turn("ext-cancel", cancellation_token=token)

    events = await store.get_events("ext-cancel")
    types = [e.type for e in events]
    # The partial delta was emitted before the raise, but the canonical
    # CancellationCompleted event must NOT appear because cancellation was
    # not our own.
    assert EventType.CANCELLATION_COMPLETED not in types


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
    """replay_session must include tool_call_id on tool messages.

    This is the regression test for the multi-turn tool loop bug: without
    tool_call_id the second provider request is structurally broken for
    OpenAI/Anthropic (they require matching IDs on tool results).
    """
    from kaji.infra.events.replay import replay_session
    from kaji.infra.events.schemas import (
        ToolCallCompleted,
        ToolCallRequested,
        ToolCallStarted,
        UserMessage,
    )
    from kaji.infra.events.store import InMemoryEventStore

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
        ToolCallStarted(
            session_id=session_id, tool_name="lookup", tool_call_id="call-abc"
        )
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
    state = replay_session(events)

    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call-abc", (
        "tool_call_id must be preserved in replay so providers can correlate results"
    )


@pytest.mark.asyncio
async def test_tool_call_id_preserved_on_failed_tool_replay():
    """TOOL_CALL_FAILED events must also carry tool_call_id through replay."""
    from kaji.infra.events.replay import replay_session
    from kaji.infra.events.schemas import (
        ToolCallFailed,
        ToolCallRequested,
        UserMessage,
    )
    from kaji.infra.events.store import InMemoryEventStore

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
    state = replay_session(events)

    tool_msgs = [m for m in state.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call-xyz"
    assert "Error:" in tool_msgs[0]["content"]


# ---------------------------------------------------------------------------
# Planner-attribute collapse (Task 9)
# ---------------------------------------------------------------------------


def test_explicit_planner_lives_on_self_planner():
    """When an explicit planner is passed, runtime.planner returns it without
    rebuilding. Same identity, plain attribute access."""
    explicit = ToolPlanner(executor=mock_executor)
    runtime = AgentRuntime(
        bus=MockEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        planner=explicit,
    )
    assert runtime.planner is explicit


def test_default_planner_lives_on_self_planner():
    """When no planner is given, runtime.planner is the lazily-built default."""
    runtime = AgentRuntime(
        bus=MockEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        tool_executor=mock_executor,
    )
    assert isinstance(runtime.planner, ToolPlanner)
    # Plain attribute, not a @property: assignment must work (regression
    # guard for the prior @property-shaped surface).
    new_planner = ToolPlanner(executor=mock_executor)
    runtime.planner = new_planner
    assert runtime.planner is new_planner


def test_planner_attribute_is_plain_not_property():
    """`AgentRuntime.planner` must be an instance attribute, not a property.
    The earlier surface had `@property def planner` AND `self._planner =
    ...`, which raised AttributeError if anything tried `self.planner = x`.
    """
    runtime = AgentRuntime(
        bus=MockEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        tool_executor=mock_executor,
    )
    # The class itself must not define `planner` as a property/descriptor.
    assert "planner" not in vars(AgentRuntime)
    # And the instance must carry it.
    assert "planner" in vars(runtime)


def test_underscore_planner_attrs_are_gone():
    """No leftover `_planner` or `_explicit_planner` book-keeping attributes
    after the collapse; the source of truth is `self.planner` only."""
    runtime = AgentRuntime(
        bus=MockEventBus(),
        store=InMemoryEventStore(),
        provider=MockProvider(),
        tool_executor=mock_executor,
    )
    assert not hasattr(runtime, "_planner")
    assert not hasattr(runtime, "_explicit_planner")
