from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import kaji

from kaji.infra.events.json import canonical_json
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.events.types import EventType
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.limits import TurnExecutionLimits
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.strategy import AgentStrategy
from kaji.runtime.agents.stream import DeltaAccumulator
from kaji.runtime.providers.anthropic import AnthropicProvider
from kaji.runtime.providers.base import (
    ProviderDiagnosticsSink,
    ProviderResponseBudget,
    RawToolCallFragment,
    ResponseBudgetDiagnostics,
    capture_provider_diagnostics,
    provider_diagnostics_scope,
)
from kaji.runtime.providers.errors import ProviderOutputLimitError
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.gemini import GeminiProvider
from kaji.runtime.providers.kimi import KimiProvider
from kaji.runtime.providers.mock import MockProvider as BuiltinMockProvider
from kaji.runtime.providers.types import (
    GenerateResponse,
    ModelResponseChunk,
    ProviderResponseLimits,
)
from kaji.runtime.tools.registry import ToolSpec


class _ScriptedProvider:
    def __init__(
        self, chunks: list[ModelResponseChunk], *, failure: Exception | None = None
    ):
        self.chunks = chunks
        self.failure = failure
        self.response_limits: ProviderResponseLimits | None = None

    async def generate(self, *_args: Any, **_kwargs: Any) -> GenerateResponse:
        return GenerateResponse(text="")

    async def generate_stream(
        self,
        *_args: Any,
        response_limits: ProviderResponseLimits | None = None,
        **_kwargs: Any,
    ) -> AsyncGenerator[ModelResponseChunk, None]:
        self.response_limits = response_limits
        for chunk in self.chunks:
            yield chunk
        if self.failure is not None:
            raise self.failure


def _runtime(
    provider: Any,
    *,
    limits: TurnExecutionLimits | None = None,
    strategy: AgentStrategy | None = None,
) -> tuple[AgentRuntime, InMemoryEventStore]:
    store = InMemoryEventStore()
    return (
        AgentRuntime(
            store=store,
            provider=provider,
            turn_execution_limits=limits,
            strategy=strategy,
        ),
        store,
    )


def test_delta_accumulator_is_scalar_safe_and_linear() -> None:
    accumulator = DeltaAccumulator(max_chunk_bytes=4_096)

    emitted: list[str] = []
    for _ in range(10_000):
        emitted.extend(accumulator.push("x"))
    emitted.extend(accumulator.push("😀"))
    residual = accumulator.flush()
    if residual is not None:
        emitted.append(residual)

    assert "".join(emitted) == ("x" * 10_000) + "😀"
    assert all(0 < len(delta.encode("utf-8")) <= 4_096 for delta in emitted)
    assert accumulator.total_bytes == 10_004
    assert accumulator.diagnostics.input_fragments == 10_001
    assert accumulator.diagnostics.output_chunks == len(emitted)
    assert accumulator.diagnostics.join_operations == len(emitted)


def test_response_limit_contract_is_public() -> None:
    assert kaji.ProviderResponseLimits is ProviderResponseLimits
    assert kaji.ProviderOutputLimitError is ProviderOutputLimitError


@pytest.mark.parametrize(
    "provider_type",
    [
        OpenAIProvider,
        AnthropicProvider,
        KimiProvider,
        GeminiProvider,
        BuiltinMockProvider,
    ],
)
def test_python_builtins_accept_the_response_limits_contract(
    provider_type: type[Any],
) -> None:
    assert "response_limits" in inspect.signature(provider_type.generate).parameters
    assert (
        "response_limits" in inspect.signature(provider_type.generate_stream).parameters
    )


@pytest.mark.asyncio
async def test_builtin_mock_enforces_limits_without_a_runtime() -> None:
    provider = BuiltinMockProvider(reply="four")
    limits = ProviderResponseLimits(text_max_bytes=3)

    with pytest.raises(ProviderOutputLimitError):
        await provider.generate([], response_limits=limits)
    with pytest.raises(ProviderOutputLimitError):
        async for _ in provider.generate_stream([], response_limits=limits):
            pass


@pytest.mark.asyncio
async def test_runtime_threads_limits_and_coalesces_exact_completion() -> None:
    provider = _ScriptedProvider([ModelResponseChunk(delta="x") for _ in range(10_000)])
    runtime, _ = _runtime(provider)

    result = await runtime.turn("hello")

    assert result.text == "x" * 10_000
    assert provider.response_limits == ProviderResponseLimits()
    deltas = [
        event.delta
        for event in result.events
        if event.type == EventType.AGENT_MESSAGE_DELTA
    ]
    completed = [
        event.content
        for event in result.events
        if event.type == EventType.AGENT_MESSAGE_COMPLETED
    ]
    assert "".join(deltas) == completed[0] == result.text
    assert len(deltas) == 3
    diagnostics = runtime.stream_diagnostics(result.session_id)
    assert diagnostics is not None
    assert diagnostics.input_fragments == 10_000
    assert diagnostics.response_join_operations == 1
    assert diagnostics.delta_join_operations == 3
    assert diagnostics.raw_fragments == 0


@pytest.mark.asyncio
async def test_text_limit_flushes_prefix_before_typed_terminal_without_completion() -> (
    None
):
    provider = _ScriptedProvider(
        [ModelResponseChunk(delta="abcd"), ModelResponseChunk(delta="é")]
    )
    runtime, store = _runtime(
        provider,
        limits=TurnExecutionLimits(
            provider_text_max_bytes=5,
            provider_response_max_bytes=16,
        ),
    )

    with pytest.raises(ProviderOutputLimitError) as raised:
        await runtime.turn("hello", session_id="limited")

    assert raised.value.dimension == "text"
    assert raised.value.limit == 5
    events = await store.get_events("limited")
    types = [event.type for event in events]
    assert EventType.AGENT_MESSAGE_COMPLETED not in types
    delta_index = types.index(EventType.AGENT_MESSAGE_DELTA)
    failed_index = types.index(EventType.AGENT_TURN_FAILED)
    assert delta_index < failed_index
    assert events[delta_index].delta == "abcd"
    failed = events[failed_index]
    assert failed.error_code == "PROVIDER_OUTPUT_LIMIT"
    assert failed.phase == "provider_stream"
    assert failed.retryable is False
    assert failed.outcome == "unknown"
    assert failed.error == "Provider output exceeded text limit of 5 bytes"


@pytest.mark.asyncio
async def test_literal_256_kib_multibyte_text_exact_and_one_byte_over() -> None:
    exact = "é" * (262_144 // 2)
    allowed, _ = _runtime(_ScriptedProvider([ModelResponseChunk(delta=exact)]))
    result = await allowed.turn("hello")
    assert result.text == exact
    deltas = [
        event.delta
        for event in result.events
        if event.type == EventType.AGENT_MESSAGE_DELTA
    ]
    assert "".join(deltas) == exact
    assert len(deltas) == 64

    rejected, store = _runtime(
        _ScriptedProvider(
            [ModelResponseChunk(delta=exact), ModelResponseChunk(delta="x")]
        )
    )
    with pytest.raises(ProviderOutputLimitError):
        await rejected.turn("hello", session_id="text-over")
    events = await store.get_events("text-over")
    assert (
        "".join(
            event.delta
            for event in events
            if event.type == EventType.AGENT_MESSAGE_DELTA
        )
        == exact
    )
    assert not any(event.type == EventType.AGENT_MESSAGE_COMPLETED for event in events)


@pytest.mark.asyncio
async def test_ordinary_provider_failure_flushes_residual_before_terminal() -> None:
    provider = _ScriptedProvider(
        [ModelResponseChunk(delta="partial")], failure=RuntimeError("provider boom")
    )
    runtime, store = _runtime(provider)

    with pytest.raises(RuntimeError, match="provider boom"):
        await runtime.turn("hello", session_id="failed")

    events = await store.get_events("failed")
    types = [event.type for event in events]
    assert types.index(EventType.AGENT_MESSAGE_DELTA) < types.index(
        EventType.AGENT_TURN_FAILED
    )
    assert EventType.AGENT_MESSAGE_COMPLETED not in types


@pytest.mark.asyncio
async def test_cancellation_flushes_residual_before_terminal() -> None:
    entered = asyncio.Event()

    class BlockingProvider(_ScriptedProvider):
        async def generate_stream(
            self,
            *_args: Any,
            response_limits: ProviderResponseLimits | None = None,
            **_kwargs: Any,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            self.response_limits = response_limits
            yield ModelResponseChunk(delta="partial")
            entered.set()
            await asyncio.Event().wait()

    provider = BlockingProvider([])
    runtime, store = _runtime(provider)
    token = CancellationToken()
    turn = asyncio.create_task(
        runtime.turn("hello", session_id="cancelled", cancellation_token=token)
    )
    await entered.wait()
    token.cancel()
    result = await turn

    assert result.text == ""
    events = await store.get_events("cancelled")
    types = [event.type for event in events]
    assert types.index(EventType.AGENT_MESSAGE_DELTA) < types.index(
        EventType.CANCELLATION_COMPLETED
    )
    assert EventType.AGENT_MESSAGE_COMPLETED not in types


@pytest.mark.asyncio
async def test_residual_delta_is_durable_before_tool_execution() -> None:
    store = InMemoryEventStore()
    spec = ToolSpec(
        name="lookup",
        description="lookup",
        parameters={"type": "object", "additionalProperties": False},
        risk="read",
    )
    observed_types: list[EventType] = []

    async def execute(_invocation: Any) -> dict[str, bool]:
        observed_types.extend(event.type for event in await store.get_events("tools"))
        return {"ok": True}

    planner = ToolPlanner(executor=execute, specs={spec.name: spec})
    provider = _ScriptedProvider(
        [
            ModelResponseChunk(
                delta="residual",
                tool_calls=[{"id": "call", "name": "lookup", "arguments": {}}],
            )
        ]
    )
    runtime = AgentRuntime(
        store=store,
        provider=provider,
        planner=planner,
        tools=[spec],
        strategy=AgentStrategy(max_iterations=1),
        default_context=TurnContext(principal_id="tester"),
    )

    await runtime.turn("hello", session_id="tools")

    assert EventType.AGENT_MESSAGE_DELTA in observed_types
    assert observed_types.index(EventType.AGENT_MESSAGE_DELTA) < observed_types.index(
        EventType.TOOL_CALL_REQUESTED
    )


@pytest.mark.asyncio
async def test_runtime_rejects_call_and_argument_limits_atomically() -> None:
    sixty_four = [
        {"id": f"call-{index}", "name": "lookup", "arguments": {}}
        for index in range(64)
    ]
    allowed, _ = _runtime(
        _ScriptedProvider([ModelResponseChunk(tool_calls=sixty_four)]),
        strategy=AgentStrategy(allow_tool_calls=False),
    )
    result = await allowed.turn("hello")
    assert not any(event.type == EventType.AGENT_TURN_FAILED for event in result.events)

    rejected, store = _runtime(
        _ScriptedProvider(
            [
                ModelResponseChunk(
                    tool_calls=sixty_four
                    + [{"id": "call-65", "name": "lookup", "arguments": {}}]
                )
            ]
        )
    )
    with pytest.raises(ProviderOutputLimitError) as raised:
        await rejected.turn("hello", session_id="calls")
    assert (raised.value.dimension, raised.value.limit) == ("tool_calls", 64)
    assert not any(
        event.type
        in {
            EventType.TOOL_CALL_REQUESTED,
            EventType.TOOL_CALL_COMPLETED,
            EventType.AGENT_MESSAGE_COMPLETED,
        }
        for event in await store.get_events("calls")
    )

    argument_rejected, _ = _runtime(
        _ScriptedProvider(
            [
                ModelResponseChunk(
                    tool_calls=[
                        {
                            "id": "call",
                            "name": "lookup",
                            "arguments": {"value": "é"},
                        }
                    ]
                )
            ]
        ),
        limits=TurnExecutionLimits(provider_tool_arguments_max_bytes=12),
    )
    with pytest.raises(ProviderOutputLimitError) as args_error:
        await argument_rejected.turn("hello")
    assert args_error.value.dimension == "tool_arguments"


def test_exact_multibyte_text_and_canonical_argument_boundaries() -> None:
    exact_text = "é" * (262_144 // 2)
    text_budget = ProviderResponseBudget()
    accepted = text_budget.accept_normalized(exact_text, [])
    assert accepted.delta == exact_text
    assert text_budget.diagnostics.text_bytes == 262_144

    with pytest.raises(ProviderOutputLimitError) as text_error:
        ProviderResponseBudget().accept_normalized(exact_text + "x", [])
    assert (text_error.value.dimension, text_error.value.limit) == (
        "text",
        262_144,
    )

    empty_encoded = canonical_json({"value": ""}, subject="tool arguments")
    exact_value = "x" * (65_536 - len(empty_encoded.encode("utf-8")))
    exact_arguments = {"value": exact_value}
    arguments_budget = ProviderResponseBudget()
    detached = arguments_budget.accept_normalized(
        "",
        [{"id": "call", "name": "lookup", "arguments": exact_arguments}],
    )
    exact_arguments["value"] = "mutated"
    assert detached.tool_calls[0]["arguments"]["value"] == exact_value

    with pytest.raises(ProviderOutputLimitError) as arguments_error:
        ProviderResponseBudget().accept_normalized(
            "",
            [
                {
                    "id": "call",
                    "name": "lookup",
                    "arguments": {"value": exact_value + "x"},
                }
            ],
        )
    assert (arguments_error.value.dimension, arguments_error.value.limit) == (
        "tool_arguments",
        65_536,
    )


def test_text_arguments_ids_and_names_share_exact_total_budget() -> None:
    budget = ProviderResponseBudget()
    fragments = tuple(
        RawToolCallFragment(
            key=index,
            starts_call=True,
            id_fragment="i",
            name_fragment="n",
            arguments_fragment="x" * 65_536,
        )
        for index in range(4)
    )
    budget.accept_raw(text="x" * 262_136, tool_fragments=fragments)
    assert budget.diagnostics.total_response_bytes == 524_288

    with pytest.raises(ProviderOutputLimitError) as raised:
        budget.accept_raw(text="x")
    assert (raised.value.dimension, raised.value.limit) == (
        "total_response",
        524_288,
    )


@pytest.mark.asyncio
async def test_empty_provider_deltas_create_no_empty_durable_events() -> None:
    runtime, _ = _runtime(
        _ScriptedProvider([ModelResponseChunk() for _ in range(10_000)])
    )

    result = await runtime.turn("hello")

    assert result.text == ""
    assert not any(
        event.type in {EventType.AGENT_MESSAGE_DELTA, EventType.AGENT_MESSAGE_COMPLETED}
        for event in result.events
    )
    diagnostics = runtime.stream_diagnostics(result.session_id)
    assert diagnostics is not None
    assert diagnostics.input_fragments == 0
    assert diagnostics.durable_delta_events == 0


@pytest.mark.asyncio
async def test_provider_diagnostics_are_isolated_per_concurrent_call_and_reset() -> (
    None
):
    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    class DiagnosticProvider(_ScriptedProvider):
        async def generate_stream(
            self,
            messages: list[dict[str, Any]],
            *_args: Any,
            response_limits: ProviderResponseLimits | None = None,
            **_kwargs: Any,
        ) -> AsyncGenerator[ModelResponseChunk, None]:
            nonlocal entered
            self.response_limits = response_limits
            prompt = next(
                message["content"]
                for message in reversed(messages)
                if message["role"] == "user"
            )
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            marker = 1 if prompt == "one" else 2
            capture_provider_diagnostics(
                ResponseBudgetDiagnostics(0, 0, 0, marker, marker)
            )
            yield ModelResponseChunk(delta=prompt)

    provider = DiagnosticProvider([])
    runtime, _ = _runtime(provider)
    first = asyncio.create_task(runtime.turn("one", session_id="one"))
    second = asyncio.create_task(runtime.turn("two", session_id="two"))
    await both_entered.wait()
    release.set()
    await asyncio.gather(first, second)

    one = runtime.stream_diagnostics("one")
    two = runtime.stream_diagnostics("two")
    assert one is not None and two is not None
    assert (one.raw_fragments, one.tool_argument_join_operations) == (1, 1)
    assert (two.raw_fragments, two.tool_argument_join_operations) == (2, 2)

    capture_provider_diagnostics(ResponseBudgetDiagnostics(0, 0, 0, 99, 99))
    assert runtime.stream_diagnostics("one") == one
    assert runtime.stream_diagnostics("two") == two


def _openai_tool_chunk(
    *,
    index: int = 0,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str = "",
    finish_reason: str | None = None,
) -> Any:
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=call_id,
                            function=SimpleNamespace(name=name, arguments=arguments),
                        )
                    ],
                ),
            )
        ],
    )


class _CloseAwareOpenAIStream:
    def __init__(self, chunks: list[Any], *, close_fails: bool = False):
        self.chunks = iter(chunks)
        self.close_called = False
        self.close_fails = close_fails

    def __aiter__(self) -> _CloseAwareOpenAIStream:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self) -> None:
        self.close_called = True
        if self.close_fails:
            raise RuntimeError("vendor close failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_openai_closes_before_oversize_arguments_are_parsed(
    close_fails: bool,
) -> None:
    empty_encoded = '{"value":""}'
    oversized = (
        '{"value":"' + ("x" * (65_537 - len(empty_encoded.encode("utf-8")))) + '"}'
    )
    stream = _CloseAwareOpenAIStream(
        [
            _openai_tool_chunk(
                call_id="call",
                name="lookup",
                arguments=oversized,
                finish_reason="tool_calls",
            )
        ],
        close_fails=close_fails,
    )

    async def create(**_kwargs: Any) -> _CloseAwareOpenAIStream:
        return stream

    provider = OpenAIProvider(api_key="test")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with patch.object(
        OpenAIProvider,
        "_finalize_stream_tool_calls",
        side_effect=AssertionError("parse must not run"),
    ):
        with pytest.raises(ProviderOutputLimitError) as raised:
            async for _ in provider.generate_stream(
                [],
                response_limits=ProviderResponseLimits(),
            ):
                pass

    assert (raised.value.dimension, raised.value.limit) == (
        "tool_arguments",
        65_536,
    )
    assert stream.close_called is True


def _split_nonempty(value: str, count: int) -> list[str]:
    width, extra = divmod(len(value), count)
    result: list[str] = []
    cursor = 0
    for index in range(count):
        length = width + (1 if index < extra else 0)
        result.append(value[cursor : cursor + length])
        cursor += length
    assert cursor == len(value)
    assert all(result)
    return result


@pytest.mark.asyncio
async def test_openai_joins_ten_thousand_argument_fragments_once_at_exact_limit() -> (
    None
):
    empty_encoded = '{"value":""}'
    exact = '{"value":"' + ("x" * (65_536 - len(empty_encoded.encode("utf-8")))) + '"}'
    fragments = _split_nonempty(exact, 10_000)
    chunks = [
        _openai_tool_chunk(
            call_id="call" if index == 0 else None,
            name="lookup" if index == 0 else None,
            arguments=fragment,
            finish_reason="tool_calls" if index == len(fragments) - 1 else None,
        )
        for index, fragment in enumerate(fragments)
    ]
    stream = _CloseAwareOpenAIStream(chunks)

    async def create(**_kwargs: Any) -> _CloseAwareOpenAIStream:
        return stream

    provider = OpenAIProvider(api_key="test")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    diagnostics = ProviderDiagnosticsSink()

    with provider_diagnostics_scope(diagnostics):
        chunks_out = [
            chunk
            async for chunk in provider.generate_stream(
                [],
                response_limits=ProviderResponseLimits(),
            )
        ]

    calls = [call for chunk in chunks_out for call in chunk.tool_calls]
    assert calls == [
        {
            "id": "call",
            "name": "lookup",
            "arguments": {"value": "x" * (len(exact) - len(empty_encoded))},
        }
    ]
    assert diagnostics.diagnostics.raw_fragments == 10_002
    assert diagnostics.diagnostics.tool_argument_join_operations == 1
    assert stream.close_called is False


def _openai_many_calls_chunk(count: int) -> Any:
    return SimpleNamespace(
        usage=None,
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=f"call-{index}",
                            function=SimpleNamespace(name="lookup", arguments="{}"),
                        )
                        for index in range(count)
                    ],
                ),
            )
        ],
    )


@pytest.mark.asyncio
async def test_openai_accepts_64_calls_and_closes_before_parsing_65() -> None:
    async def collect(
        count: int,
    ) -> tuple[list[ModelResponseChunk], _CloseAwareOpenAIStream]:
        stream = _CloseAwareOpenAIStream([_openai_many_calls_chunk(count)])

        async def create(**_kwargs: Any) -> _CloseAwareOpenAIStream:
            return stream

        provider = OpenAIProvider(api_key="test")
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        chunks = [chunk async for chunk in provider.generate_stream([])]
        return chunks, stream

    accepted, accepted_stream = await collect(64)
    assert sum(len(chunk.tool_calls) for chunk in accepted) == 64
    assert accepted_stream.close_called is False

    stream = _CloseAwareOpenAIStream([_openai_many_calls_chunk(65)])

    async def create(**_kwargs: Any) -> _CloseAwareOpenAIStream:
        return stream

    provider = OpenAIProvider(api_key="test")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    with patch.object(
        OpenAIProvider,
        "_finalize_stream_tool_calls",
        side_effect=AssertionError("parse must not run"),
    ):
        with pytest.raises(ProviderOutputLimitError) as raised:
            async for _ in provider.generate_stream([]):
                pass
    assert (raised.value.dimension, raised.value.limit) == ("tool_calls", 64)
    assert stream.close_called is True


@pytest.mark.asyncio
@pytest.mark.parametrize("close_fails", [False, True])
async def test_anthropic_closes_before_oversize_arguments_are_parsed(
    close_fails: bool,
) -> None:
    exited = False
    empty_encoded = '{"value":""}'
    oversized = (
        '{"value":"' + ("x" * (65_537 - len(empty_encoded.encode("utf-8")))) + '"}'
    )

    class Stream:
        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            nonlocal exited
            exited = True
            if close_fails:
                raise RuntimeError("vendor close failed")

        def __aiter__(self) -> AsyncGenerator[Any, None]:
            async def events() -> AsyncGenerator[Any, None]:
                yield SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(
                        type="tool_use", id="call", name="lookup"
                    ),
                )
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(
                        type="input_json_delta", partial_json=oversized
                    ),
                )
                yield SimpleNamespace(type="content_block_stop")

            return events()

    provider = AnthropicProvider(api_key="test")
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **_kwargs: Stream())
    )
    with patch.object(
        AnthropicProvider,
        "_parse_tool_args",
        side_effect=AssertionError("parse must not run"),
    ):
        with pytest.raises(ProviderOutputLimitError) as raised:
            async for _ in provider.generate_stream(
                [],
                response_limits=ProviderResponseLimits(),
            ):
                pass

    assert (raised.value.dimension, raised.value.limit) == (
        "tool_arguments",
        65_536,
    )
    assert exited is True


@pytest.mark.asyncio
async def test_anthropic_accepts_exact_arguments_with_one_join() -> None:
    empty_encoded = '{"value":""}'
    exact = '{"value":"' + ("x" * (65_536 - len(empty_encoded.encode("utf-8")))) + '"}'
    exited = False

    class Stream:
        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            nonlocal exited
            exited = True

        def __aiter__(self) -> AsyncGenerator[Any, None]:
            async def events() -> AsyncGenerator[Any, None]:
                yield SimpleNamespace(
                    type="content_block_start",
                    content_block=SimpleNamespace(
                        type="tool_use", id="call", name="lookup"
                    ),
                )
                for fragment in _split_nonempty(exact, 10_000):
                    yield SimpleNamespace(
                        type="content_block_delta",
                        delta=SimpleNamespace(
                            type="input_json_delta", partial_json=fragment
                        ),
                    )
                yield SimpleNamespace(type="content_block_stop")

            return events()

    provider = AnthropicProvider(api_key="test")
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **_kwargs: Stream())
    )
    diagnostics = ProviderDiagnosticsSink()
    with provider_diagnostics_scope(diagnostics):
        chunks = [chunk async for chunk in provider.generate_stream([])]

    calls = [call for chunk in chunks for call in chunk.tool_calls]
    assert calls[0]["arguments"] == {"value": "x" * (len(exact) - len(empty_encoded))}
    assert diagnostics.diagnostics.raw_fragments == 10_002
    assert diagnostics.diagnostics.tool_argument_join_operations == 1
    assert exited is True


@pytest.mark.asyncio
async def test_anthropic_accepts_64_calls_and_rejects_65_before_parse() -> None:
    class Stream:
        def __init__(self, events: list[Any]):
            self.events = events
            self.exited = False

        async def __aenter__(self) -> Stream:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            self.exited = True

        def __aiter__(self) -> AsyncGenerator[Any, None]:
            async def iterate() -> AsyncGenerator[Any, None]:
                for event in self.events:
                    yield event

            return iterate()

    def start(index: int) -> Any:
        return SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(
                type="tool_use", id=f"call-{index}", name="lookup"
            ),
        )

    allowed_events: list[Any] = []
    for index in range(64):
        allowed_events.extend(
            [
                start(index),
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="input_json_delta", partial_json="{}"),
                ),
                SimpleNamespace(type="content_block_stop"),
            ]
        )
    allowed_stream = Stream(allowed_events)
    allowed = AnthropicProvider(api_key="test")
    allowed._client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **_kwargs: allowed_stream)
    )
    chunks = [chunk async for chunk in allowed.generate_stream([])]
    assert sum(len(chunk.tool_calls) for chunk in chunks) == 64
    assert allowed_stream.exited is True

    rejected_stream = Stream([start(index) for index in range(65)])
    rejected = AnthropicProvider(api_key="test")
    rejected._client = SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **_kwargs: rejected_stream)
    )
    with patch.object(
        AnthropicProvider,
        "_parse_tool_args",
        side_effect=AssertionError("parse must not run"),
    ):
        with pytest.raises(ProviderOutputLimitError) as raised:
            async for _ in rejected.generate_stream([]):
                pass
    assert (raised.value.dimension, raised.value.limit) == ("tool_calls", 64)
    assert rejected_stream.exited is True
