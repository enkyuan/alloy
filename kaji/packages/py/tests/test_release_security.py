from __future__ import annotations

# redis-integration: exercises Redis-backed redaction with a mocked client.

import asyncio
import ast
import httpx
import json
import logging
from pathlib import Path
import re
import traceback
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from kaji.infra.events.bus import EventBus
from kaji.infra.events.errors import EventSchemaIncompatibleError
from kaji.infra.events.schemas import validate_event_json
from kaji.infra.events.store import InMemoryEventStore
from kaji.infra.observability.protocols import TraceSink, start_span
from kaji.infra.realtime.history_ops import get_history
from kaji.knowledge.rag import DocumentRAG
from kaji.modalities.voice.tts.gemini_provider import GeminiTTSProvider
from kaji.runtime.agents.runtime import AgentRuntime
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import ToolExecutionContext, ToolInvocation
from kaji.runtime.providers.anthropic import AnthropicProvider
from kaji.runtime.providers.errors import (
    ProviderError,
    provider_error_from_exception,
)
from kaji.runtime.providers.gemini import GeminiService
from kaji.runtime.providers.kimi import KimiProvider
from kaji.runtime.providers.mock import MockProvider
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.tools.execution import ToolExecutionController
from kaji.runtime.tools.registry import ToolSpec
from kaji.runtime.tools.retriever import ToolRetriever


REPO_ROOT = Path(__file__).resolve().parents[4]
REVIEWED_ACTION_PINS = {
    "actions/checkout": "34e114876b0b11c390a56381ad16ebd13914f8d5",
    "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
    "actions/download-artifact": "d3f86a106a0bac45b974a628896c90dbdf5c8093",
    "actions/github-script": "f28e40c7f34bde8b3046d885e986cb6290c5673b",
    "actions/attest-build-provenance": "e8998f949152b193b063cb0ec769d69d929409be",
    "anchore/sbom-action": "fbfd9c6c189226748411491745178e0c2017392d",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    "astral-sh/setup-uv": "caf0cab7a618c569241d31dcd442f54681755d39",
    "oven-sh/setup-bun": "0c5077e51419868618aeaa5fe8019c62421857d6",
    "actions/cache": "0057852bfaa89a56745cba8c7296529d2fc39830",
}


def _assert_sanitized_provider_error(error: ProviderError, secret: str) -> None:
    assert not hasattr(error, "response_text")
    assert not hasattr(error, "cause")
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)
    assert secret not in "".join(traceback.format_exception(error))


def test_provider_argument_parse_logs_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-tool-argument-secret"
    caplog.set_level(logging.WARNING)

    OpenAIProvider._parse_tool_calls(
        [
            SimpleNamespace(
                id="call",
                function=SimpleNamespace(
                    name="lookup",
                    arguments=f'{{"token":"{secret}"',
                ),
            )
        ]
    )
    AnthropicProvider._parse_tool_args(f'{{"token":"{secret}"', "lookup", "call")

    assert secret not in caplog.text
    assert "arguments redacted" in caplog.text


def test_provider_public_exception_string_is_redacted() -> None:
    secret = "sk-provider-key-secret"
    error = provider_error_from_exception(
        service="openai",
        action="request",
        error=RuntimeError(f"request failed with {secret}"),
    )

    assert secret not in str(error)
    assert str(error) == "openai request failed"
    assert not hasattr(error, "response_text")
    assert not hasattr(error, "cause")


def test_provider_traceback_and_trace_sink_do_not_retain_vendor_cause() -> None:
    secret = "sk-provider-traceback-secret"
    normalized: ProviderError | None = None
    try:
        raise RuntimeError(secret)
    except RuntimeError as vendor_error:
        normalized = provider_error_from_exception(
            service="openai",
            action="stream",
            error=vendor_error,
        )

    assert normalized is not None
    try:
        raise normalized from None
    except ProviderError as error:
        rendered = "".join(traceback.format_exception(error))
        assert secret not in rendered
        _assert_sanitized_provider_error(error, secret)

        recorded: list[BaseException] = []

        class Span:
            def set_attribute(self, _name: str, _value: str) -> None:
                return None

            def record_error(self, captured: BaseException) -> None:
                recorded.append(captured)

            def end(self) -> None:
                return None

        class Trace:
            def start_span(self, _name: str, _attributes: object) -> Span:
                return Span()

        start_span(cast(TraceSink, Trace()), "kaji.provider", {}).record_error(error)
        assert secret not in " ".join(str(item) for item in recorded)


class _FailingProviderStream:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __aiter__(self) -> _FailingProviderStream:
        return self

    async def __anext__(self) -> object:
        raise self.error

    async def __aenter__(self) -> _FailingProviderStream:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _provider_with_failing_stream(
    provider_name: str, error: BaseException
) -> OpenAIProvider | AnthropicProvider:
    stream = _FailingProviderStream(error)
    if provider_name == "openai":

        class Completions:
            async def create(self, **_kwargs: object) -> _FailingProviderStream:
                return stream

        provider = OpenAIProvider(api_key="configured")
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        )
        return provider

    class Messages:
        def stream(self, **_kwargs: object) -> _FailingProviderStream:
            return stream

    provider = AnthropicProvider(api_key="configured")
    provider._client = SimpleNamespace(messages=Messages())
    return provider


def _provider_with_failing_open(
    provider_name: str, error: Exception
) -> OpenAIProvider | AnthropicProvider:
    if provider_name == "openai":

        class Completions:
            async def create(self, **_kwargs: object) -> object:
                raise error

        provider = OpenAIProvider(api_key="configured")
        provider._client = SimpleNamespace(
            chat=SimpleNamespace(completions=Completions())
        )
        return provider

    class Messages:
        async def create(self, **_kwargs: object) -> object:
            raise error

        def stream(self, **_kwargs: object) -> object:
            raise error

    provider = AnthropicProvider(api_key="configured")
    provider._client = SimpleNamespace(messages=Messages())
    return provider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
@pytest.mark.parametrize("stream", [False, True], ids=["request", "stream-open"])
async def test_provider_open_failure_does_not_retain_vendor_exception(
    provider_name: str,
    stream: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"sk-{provider_name}-{'stream' if stream else 'request'}-open-secret"
    provider = _provider_with_failing_open(provider_name, RuntimeError(secret))
    caplog.set_level(logging.ERROR)

    with pytest.raises(ProviderError) as captured:
        if stream:
            _ = [
                chunk
                async for chunk in provider.generate_stream(
                    messages=[{"role": "user", "content": "hello"}]
                )
            ]
        else:
            await provider.generate(messages=[{"role": "user", "content": "hello"}])

    error = captured.value
    assert error.service == provider_name
    assert error.action == ("stream" if stream else "request")
    _assert_sanitized_provider_error(error, secret)
    assert secret not in caplog.text
    assert "details redacted" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
async def test_provider_midstream_failure_is_normalized_without_secret_retention(
    provider_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"sk-{provider_name}-midstream-secret"
    provider = _provider_with_failing_stream(provider_name, RuntimeError(secret))
    caplog.set_level(logging.ERROR)

    with pytest.raises(ProviderError) as captured:
        _ = [
            chunk
            async for chunk in provider.generate_stream(
                messages=[{"role": "user", "content": "hello"}]
            )
        ]

    error = captured.value
    assert error.service == provider_name
    assert error.action == "stream"
    _assert_sanitized_provider_error(error, secret)
    assert secret not in caplog.text
    assert "details redacted" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
async def test_provider_midstream_cancellation_is_not_normalized(
    provider_name: str,
) -> None:
    provider = _provider_with_failing_stream(
        provider_name, asyncio.CancelledError("cancelled")
    )

    with pytest.raises(asyncio.CancelledError):
        _ = [
            chunk
            async for chunk in provider.generate_stream(
                messages=[{"role": "user", "content": "hello"}]
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True], ids=["request", "stream"])
async def test_kimi_transport_failure_does_not_retain_vendor_exception(
    stream: bool,
) -> None:
    secret = f"sk-kimi-{'stream' if stream else 'request'}-transport-secret"

    class Client:
        async def post(self, *_args: object, **_kwargs: object) -> object:
            raise httpx.ConnectError(secret)

        def stream(self, *_args: object, **_kwargs: object) -> object:
            raise httpx.ConnectError(secret)

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    provider = KimiProvider(api_key="configured")
    with (
        patch("httpx.AsyncClient", return_value=Client()),
        pytest.raises(ProviderError) as captured,
    ):
        if stream:
            _ = [
                chunk
                async for chunk in provider.generate_stream(
                    messages=[{"role": "user", "content": "hello"}]
                )
            ]
        else:
            await provider.generate(messages=[{"role": "user", "content": "hello"}])

    error = captured.value
    assert error.service == "kimi"
    assert error.action == ("stream" if stream else "generate")
    _assert_sanitized_provider_error(error, secret)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_action"),
    [
        ("generate", "generate"),
        ("embed", "embed"),
        ("chat", "chat"),
        ("stream", "stream"),
        ("chat-stream", "stream"),
    ],
)
async def test_gemini_failure_does_not_retain_vendor_exception(
    operation: str,
    expected_action: str,
) -> None:
    secret = f"sk-gemini-{operation}-secret"

    class Models:
        def generate_content(self, **_kwargs: object) -> object:
            raise RuntimeError(secret)

        def embed_content(self, **_kwargs: object) -> object:
            raise RuntimeError(secret)

        def generate_content_stream(self, **_kwargs: object) -> object:
            raise RuntimeError(secret)

    service = object.__new__(GeminiService)
    service.client = SimpleNamespace(models=Models())
    service.model = "gemini-test"
    service.embedding_model = "gemini-embedding-test"

    with pytest.raises(ProviderError) as captured:
        if operation == "generate":
            await service.generate_response("hello")
        elif operation == "embed":
            await service.embed_text("hello")
        elif operation == "chat":
            await service.generate_chat_response([])
        elif operation == "stream":
            _ = [chunk async for chunk in service.generate_streaming_response("hello")]
        else:
            _ = [chunk async for chunk in service.generate_chat_stream([])]

    error = captured.value
    assert error.service == "gemini"
    assert error.action == expected_action
    _assert_sanitized_provider_error(error, secret)


def test_trace_error_details_are_redacted() -> None:
    recorded: list[BaseException] = []

    class Span:
        def set_attribute(self, _name: str, _value: str) -> None:
            return None

        def record_error(self, error: BaseException) -> None:
            recorded.append(error)

        def end(self) -> None:
            return None

    class Trace:
        def start_span(self, _name: str, _attributes: object) -> Span:
            return Span()

    secret = "sk-trace-secret"
    span = start_span(cast(TraceSink, Trace()), "kaji.turn", {})
    span.record_error(RuntimeError(secret))

    assert len(recorded) == 1
    assert secret not in str(recorded[0])
    assert str(recorded[0]) == "RuntimeError: details redacted"


@pytest.mark.asyncio
async def test_provider_tool_and_start_failures_are_redacted_at_trace_boundary() -> (
    None
):
    recorded: list[BaseException] = []

    class Span:
        def set_attribute(self, _name: str, _value: str) -> None:
            return None

        def record_error(self, error: BaseException) -> None:
            recorded.append(error)

        def end(self) -> None:
            return None

    class Trace:
        def start_span(self, _name: str, _attributes: object) -> Span:
            return Span()

    trace = cast(TraceSink, Trace())
    provider_failure = RuntimeError("sk-provider-runtime-secret")

    class FailingProvider:
        async def generate(self, *_args: object, **_kwargs: object) -> object:
            raise provider_failure

        async def generate_stream(self, *_args: object, **_kwargs: object) -> Any:
            raise provider_failure
            yield  # pragma: no cover

    runtime = AgentRuntime(
        store=InMemoryEventStore(),
        provider=cast(Any, FailingProvider()),
        trace_sink=trace,
    )
    with pytest.raises(RuntimeError) as provider_captured:
        await runtime.turn("hello")
    assert provider_captured.value is provider_failure

    def invocation(call_id: str) -> ToolInvocation:
        return ToolInvocation(
            name="failing-tool",
            arguments={},
            context=ToolExecutionContext(
                principal_id="principal",
                session_id=f"session-{call_id}",
                turn_id="turn",
                request_id="request",
                trace_id="trace",
                tool_call_id=call_id,
                idempotency_key=f"session-{call_id}:{call_id}",
                cancellation_token=CancellationToken(),
                deadline_monotonic=None,
                db=None,
                metadata={},
            ),
        )

    spec = ToolSpec(
        name="failing-tool",
        description="failure test",
        parameters={},
        risk="read",
    )
    tool_failure = RuntimeError("sk-tool-runtime-secret")

    async def fail_tool(_invocation: ToolInvocation) -> object:
        raise tool_failure

    async def started() -> None:
        return None

    controller = ToolExecutionController(trace_sink=trace)
    outcome = await controller.execute(
        invocation("tool-failure"), spec, fail_tool, started
    )
    assert outcome.failure is not None
    assert tool_failure.args[0] not in repr(outcome)

    start_failure = RuntimeError("sk-start-callback-secret")

    async def fail_start() -> None:
        raise start_failure

    with pytest.raises(RuntimeError) as start_captured:
        await controller.execute(
            invocation("start-failure"), spec, fail_tool, fail_start
        )
    assert start_captured.value is start_failure

    rendered = " ".join(str(item) for item in recorded)
    assert str(provider_failure) not in rendered
    assert str(tool_failure) not in rendered
    assert str(start_failure) not in rendered
    assert "details redacted" in rendered


@pytest.mark.asyncio
async def test_kimi_response_body_is_redacted_from_logs_and_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-kimi-response-secret"

    class Response:
        status_code = 500
        text = secret

    class Client:
        async def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    caplog.set_level(logging.ERROR)
    with (
        patch("httpx.AsyncClient", return_value=Client()),
        pytest.raises(ProviderError) as captured,
    ):
        await KimiProvider(api_key="configured").generate(
            messages=[{"role": "user", "content": "hello"}]
        )

    assert not hasattr(captured.value, "response_text")
    assert secret not in str(captured.value)
    assert secret not in caplog.text
    assert "response redacted" in caplog.text


@pytest.mark.asyncio
async def test_kimi_invalid_json_failure_does_not_retain_parser_exception() -> None:
    secret = "sk-kimi-invalid-json-parser-secret"

    class Response:
        status_code = 200

        def json(self) -> object:
            raise ValueError(secret)

    class Client:
        async def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

        async def __aenter__(self) -> Client:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    with (
        patch("httpx.AsyncClient", return_value=Client()),
        pytest.raises(ProviderError) as captured,
    ):
        await KimiProvider(api_key="configured").generate(
            messages=[{"role": "user", "content": "hello"}]
        )

    _assert_sanitized_provider_error(captured.value, secret)


@pytest.mark.asyncio
async def test_gemini_tts_stream_error_log_is_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-gemini-tts-secret"

    class Models:
        def generate_content_stream(self, **_kwargs: object) -> object:
            raise RuntimeError(secret)

    service = SimpleNamespace(
        client=SimpleNamespace(models=Models()),
        model="model",
        build_config=lambda: None,
    )
    caplog.set_level(logging.ERROR)

    chunks = [
        chunk async for chunk in GeminiTTSProvider(cast(Any, service)).stream("hello")
    ]

    assert chunks == []
    assert secret not in caplog.text
    assert "details redacted" in caplog.text


@pytest.mark.asyncio
async def test_runtime_and_document_rag_failure_logs_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-rag-provider-secret"

    class BrokenEmbedder:
        async def embed(self, text: str) -> list[float]:
            _ = text
            raise RuntimeError(secret)

    class BrokenRag:
        async def retrieve(self, _query: str, *, top_k: int) -> list[object]:
            _ = top_k
            raise RuntimeError(secret)

    caplog.set_level(logging.WARNING)
    assert await DocumentRAG(embedder=BrokenEmbedder()).retrieve("query") == []

    runtime = AgentRuntime(
        store=InMemoryEventStore(),
        provider=MockProvider(reply="ok"),
        rag=BrokenRag(),
    )
    assert (await runtime.turn("hello")).text == "ok"

    assert secret not in caplog.text
    assert "Failed to embed RAG query (RuntimeError; details redacted)" in caplog.text
    assert "RAG retrieval failed (RuntimeError; details redacted)" in caplog.text


@pytest.mark.asyncio
async def test_tool_execution_and_retriever_failure_logs_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-tool-background-secret"
    controller = ToolExecutionController()

    async def fail_setup() -> None:
        raise RuntimeError(secret)

    pending = controller._start_setup(
        session_id="session",
        call_id="call",
        operation=fail_setup,
    )
    caplog.set_level(logging.WARNING)
    await controller._settle_background_setup(pending)

    class BrokenEmbedder:
        async def embed(self, text: str) -> list[float]:
            _ = text
            raise RuntimeError(secret)

    retriever = ToolRetriever(embedder=BrokenEmbedder())
    retriever._initialized = True
    retriever._embeddings = {"tool": [1.0]}
    await retriever.get_top_tools("query")

    assert secret not in caplog.text
    assert (
        "Background tool setup failed (RuntimeError; details redacted)" in caplog.text
    )
    assert (
        "Failed to embed query for tool RAG (RuntimeError; details redacted)"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_redis_connection_logs_redact_credential_bearing_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from kaji.infra.realtime import redis as redis_module

    secret = "sk-redis-password-secret"
    url = f"redis://user:{secret}@redis.example:6379/0"
    saved = (
        redis_module.redis_client,
        redis_module.redis_stream_client,
        redis_module.redis_binary_client,
    )
    redis_module.redis_client = None
    redis_module.redis_stream_client = None
    redis_module.redis_binary_client = None
    fake_client = object()
    fake_module = SimpleNamespace(from_url=lambda *_args, **_kwargs: fake_client)
    caplog.set_level(logging.INFO)
    try:
        with (
            patch.object(
                redis_module,
                "get_settings",
                return_value=SimpleNamespace(REDIS_URL=url),
            ),
            patch.object(redis_module, "_get_redis_module", return_value=fake_module),
        ):
            assert await redis_module.get_redis_client() is fake_client
            assert await redis_module.get_redis_stream_client() is fake_client
            assert await redis_module.get_redis_binary_client() is fake_client
    finally:
        (
            redis_module.redis_client,
            redis_module.redis_stream_client,
            redis_module.redis_binary_client,
        ) = saved

    assert secret not in caplog.text
    assert "endpoint and credentials redacted" in caplog.text


@pytest.mark.asyncio
async def test_gemini_context_cache_exception_log_is_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-gemini-cache-secret"

    class Models:
        def count_tokens(self, **_kwargs: object) -> object:
            raise RuntimeError(secret)

    service = object.__new__(GeminiService)
    service.client = SimpleNamespace(models=Models())
    service.model = "gemini-test"
    service._active_caches = {}
    caplog.set_level(logging.WARNING)

    result = await service._get_active_cache(
        "system",
        [{"role": "user", "content": str(index)} for index in range(3)],
        None,
    )

    assert result is None
    assert secret not in caplog.text
    assert "GCP Context Cache (RuntimeError; details redacted)" in caplog.text


class _KimiStreamResponse:
    def __init__(self, status_code: int, lines: list[str], secret: str) -> None:
        self.status_code = status_code
        self._lines = lines
        self._secret = secret
        self.body_read = False

    async def aread(self) -> bytes:
        self.body_read = True
        return self._secret.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _KimiStreamContext:
    def __init__(self, response: _KimiStreamResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _KimiStreamResponse:
        return self.response

    async def __aexit__(self, *_args: object) -> None:
        return None


class _KimiStreamClient:
    def __init__(self, response: _KimiStreamResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _KimiStreamClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def stream(self, *_args: object, **_kwargs: object) -> _KimiStreamContext:
        return _KimiStreamContext(self.response)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["http", "invalid-json"])
async def test_kimi_stream_failures_do_not_retain_response_payload(
    mode: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"sk-kimi-stream-{mode}-secret"
    response = (
        _KimiStreamResponse(502, [], secret)
        if mode == "http"
        else _KimiStreamResponse(200, [f"data: {{{secret}"], secret)
    )
    caplog.set_level(logging.ERROR)

    with (
        patch("httpx.AsyncClient", return_value=_KimiStreamClient(response)),
        pytest.raises(ProviderError) as captured,
    ):
        _ = [
            chunk
            async for chunk in KimiProvider(api_key="configured").generate_stream(
                messages=[{"role": "user", "content": "hello"}]
            )
        ]

    error = captured.value
    _assert_sanitized_provider_error(error, secret)
    assert secret not in caplog.text
    if mode == "http":
        assert response.body_read is False
        assert "response redacted" in caplog.text


@pytest.mark.parametrize(
    "after_sequence",
    [0, 1],
    ids=["no-partial-yield", "no-cursor-advance"],
)
@pytest.mark.asyncio
async def test_redis_bus_rejects_an_entire_batch_before_yielding(
    caplog: pytest.LogCaptureFixture,
    after_sequence: int,
) -> None:
    secret = "sk-event-stream-payload-secret"
    invalid = json.dumps(
        {
            "id": "event-2",
            "version": "1.0",
            "timestamp": 1.0,
            "type": "tool.call.requested",
            "session_id": "session",
            "turn_id": "turn",
            "tool_name": "tool",
            "tool_call_id": "call",
            "tool_args": {"secret": secret + "x" * 70_000},
            "metadata": {},
            "sequence": 2,
        }
    )
    valid = json.dumps(
        {
            "id": "event-1",
            "version": "1.0",
            "timestamp": 1.0,
            "type": "tool.call.requested",
            "session_id": "session",
            "turn_id": "turn",
            "tool_name": "tool",
            "tool_call_id": "call-1",
            "tool_args": {},
            "metadata": {},
            "sequence": 1,
        }
    )

    with pytest.raises(EventSchemaIncompatibleError) as direct:
        validate_event_json(invalid)
    assert direct.value.path == "/tool_args"
    assert secret not in str(direct.value)
    assert len(str(direct.value)) < 2_000

    class Redis:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        async def xread(
            self,
            streams: dict[str, str],
            **_kwargs: object,
        ) -> list[list[object]]:
            self.calls.append(streams)
            if len(self.calls) > 1:
                raise AssertionError("incompatible batches must not advance")
            return [
                [
                    b"stream",
                    [
                        (b"1-0", {b"payload": valid.encode()}),
                        (b"2-0", {b"payload": invalid.encode()}),
                    ],
                ]
            ]

    redis = Redis()
    caplog.set_level(logging.ERROR)
    with patch(
        "kaji.infra.realtime.redis.get_redis_stream_client",
        new=AsyncMock(return_value=redis),
    ):
        stream = EventBus().subscribe("session", after_sequence=after_sequence)
        with pytest.raises(EventSchemaIncompatibleError) as raised:
            await anext(stream)

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == "/tool_args"
    assert redis.calls == [{"kaji:events:session": "0"}]
    assert secret not in caplog.text
    assert "payload and details redacted" in caplog.text


@pytest.mark.parametrize(
    "data",
    [
        {b"payload": b"\xff"},
        {},
    ],
    ids=["malformed-utf8", "missing-payload"],
)
@pytest.mark.asyncio
async def test_redis_bus_normalizes_malformed_payloads(
    data: dict[bytes, bytes],
) -> None:
    class Redis:
        def __init__(self) -> None:
            self.calls = 0

        async def xread(self, *_args: object, **_kwargs: object):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("incompatible batches must not advance")
            return [[b"stream", [(b"1-0", data)]]]

    redis = Redis()
    raw_client = AsyncMock(return_value=redis)
    decoded_client = AsyncMock(
        side_effect=AssertionError("stream payloads require the raw Redis client")
    )
    with (
        patch(
            "kaji.infra.realtime.redis.get_redis_stream_client",
            new=raw_client,
        ),
        patch(
            "kaji.infra.realtime.redis.get_redis_client",
            new=decoded_client,
        ),
    ):
        stream = EventBus().subscribe("session")
        with pytest.raises(EventSchemaIncompatibleError) as raised:
            await anext(stream)

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == "/"
    assert redis.calls == 1
    raw_client.assert_awaited_once_with()
    decoded_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_bus_rejects_cross_session_rows() -> None:
    raw = json.dumps(
        {
            "id": "event",
            "version": "1.0",
            "timestamp": 1.0,
            "type": "tool.call.requested",
            "session_id": "other-session",
            "turn_id": "turn",
            "tool_name": "tool",
            "tool_call_id": "call",
            "tool_args": {},
            "metadata": {},
            "sequence": 1,
        }
    ).encode()

    class Redis:
        async def xread(self, *_args: object, **_kwargs: object):
            return [[b"stream", [(b"1-0", {b"payload": raw})]]]

    with patch(
        "kaji.infra.realtime.redis.get_redis_stream_client",
        new=AsyncMock(return_value=Redis()),
    ):
        stream = EventBus().subscribe("session")
        with pytest.raises(EventSchemaIncompatibleError) as raised:
            await anext(stream)

    assert raised.value.code == "EVENT_SCHEMA_INCOMPATIBLE"
    assert raised.value.path == "/session_id"


def test_production_logging_calls_have_no_raw_exception_or_traceback_fields() -> None:
    sdk_root = Path(__file__).resolve().parents[1]
    relatives = (
        "src/integrations/keychain.py",
        "src/integrations/oauth.py",
        "src/infra/realtime/history_ops.py",
    )
    for relative in relatives:
        source = (sdk_root / relative).read_text()
        assert "logger.exception" not in source
        assert "exc_info=True" not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "logger"
            ):
                continue
            rendered = ast.unparse(node)
            assert "str(error)" not in rendered
            assert "str(outbox_error)" not in rendered
            assert "context" not in rendered
            assert "**extras" not in rendered


@pytest.mark.asyncio
async def test_history_failure_logs_are_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-structured-log-secret"
    caplog.set_level(logging.WARNING)

    class HistoryRedis:
        async def lrange(self, *_args: object) -> list[bytes]:
            return [f'{{"secret":"{secret}"'.encode()]

    assert await get_history(HistoryRedis(), "user") == []

    rendered = caplog.text + repr([record.__dict__ for record in caplog.records])
    assert secret not in rendered
    assert "details redacted" in caplog.text


def test_kaji_ci_uses_only_reviewed_action_pins_with_release_annotations() -> None:
    relatives = (
        ".github/workflows/python.test.yml",
        ".github/workflows/python.lint.yml",
        ".github/workflows/python.format.yml",
        ".github/workflows/ts.test.yml",
        ".github/workflows/ts.lint.yml",
        ".github/workflows/ts.format.yml",
        ".github/workflows/ast-grep.test.yml",
        ".github/workflows/kaji.benchmark.yml",
        ".github/workflows/kaji.gate.yml",
        ".github/workflows/kaji.rehearsal.yml",
        ".github/workflows/kaji.publish.yml",
        ".github/workflows/kaji.handoff.trusted.yml",
        ".github/actions/setup-python-uv/action.yml",
        ".github/actions/setup-bun-cache/action.yml",
    )

    for relative in relatives:
        source = (REPO_ROOT / relative).read_text()
        references = re.findall(
            r"^\s*(?:-\s*)?uses:\s+([^\s#]+)(?:\s+#\s+([^\s]+))?\s*$",
            source,
            re.MULTILINE,
        )
        for reference, release in references:
            if reference.startswith("./"):
                continue
            action, revision = reference.rsplit("@", 1)
            assert revision == REVIEWED_ACTION_PINS[action]
            assert re.fullmatch(r"[0-9a-f]{40}", revision)
            assert re.fullmatch(r"v\d[^\s]*", release)


def _workflow_step_blocks(source: str, name: str) -> list[str]:
    return re.findall(
        rf"(?ms)^      - name: {re.escape(name)}\n.*?(?=^      - (?:name:|uses:|if:)|\Z)",
        source,
    )


def _literal_paths(block: str, key: str) -> list[str]:
    marker = f"          {key}: |\n"
    assert marker in block
    tail = block.split(marker, 1)[1]
    paths: list[str] = []
    for line in tail.splitlines():
        if not line.startswith("            "):
            break
        paths.append(line.strip())
    return paths


def _assert_trusted_handoff_workflow_source(source: str) -> None:
    assert source.startswith("name: handoff / kaji\n\n")
    assert "  workflow_call:" in source
    assert re.search(
        r"(?ms)^    secrets:\n      node_auth_token:\n        required: false\n", source
    )
    assert "github_token:" not in source
    assert "secrets.github_token" not in source
    assert "secrets: inherit" not in source
    assert "expected_sha" not in source
    assert re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", source) == [
        "stage",
        "node",
        "finalize",
    ]
    assert "timeout-minutes: 90" in source
    assert source.count("timeout-minutes: 30") == 2
    assert "matrix:\n        node: [22, 24]" in source
    assert not re.search(r"(?m)^    continue-on-error:", source)
    assert all(
        value == "false"
        for value in re.findall(r"(?m)^        continue-on-error:\s*(\S+)\s*$", source)
    )
    assert not re.search(r"(?m)^    if:", source)
    assert re.findall(r"(?m)^        if:\s*(.+?)\s*$", source) == [
        "${{ inputs.mode == 'internal-evaluation' }}",
        "${{ inputs.mode == 'release' }}",
    ]
    internal_preflight = _workflow_step_blocks(
        source, "Preflight internal-evaluation handoff"
    )
    release_preflight = _workflow_step_blocks(source, "Preflight release handoff")
    assert len(internal_preflight) == len(release_preflight) == 1
    assert "if: ${{ inputs.mode == 'internal-evaluation' }}" in internal_preflight[0]
    assert "if: ${{ inputs.mode == 'release' }}" in release_preflight[0]

    guards = _workflow_step_blocks(
        source, "Guard called workflow identity and candidate ref"
    )
    assert len(guards) == 3
    for guard in guards:
        for field in (
            "${{ job.workflow_repository }}",
            "${{ job.workflow_file_path }}",
            "${{ job.workflow_sha }}",
            "${{ job.workflow_ref }}",
            "${{ github.repository }}",
            "${{ github.sha }}",
            "${{ github.ref }}",
        ):
            assert field in guard
        assert 'test "$CALLED_WORKFLOW_REPOSITORY" = "enkyuan/alloy"' in guard
        assert (
            'test "$CALLED_WORKFLOW_FILE_PATH" = '
            '".github/workflows/kaji.handoff.trusted.yml"'
        ) in guard
        assert (
            "$CALLED_WORKFLOW_REPOSITORY/$CALLED_WORKFLOW_FILE_PATH@"
            "$CALLED_WORKFLOW_SHA"
        ) in guard
        assert 'test "$CALLER_REPOSITORY" = "enkyuan/alloy"' in guard
        assert 'test "$CANDIDATE_REF" = "refs/heads/main"' in guard
        assert 'test "$CANDIDATE_REF" = "refs/tags/$HANDOFF_TAG_NAME"' in guard

    assert len(re.findall(r"(?m)^          GH_TOKEN:", source)) == 1
    assert "GH_TOKEN: ${{ github.token }}" in source
    assert source.count("${{ github.token }}") == 1
    assert len(re.findall(r"(?m)^          NODE_AUTH_TOKEN:", source)) == 1
    assert "NODE_AUTH_TOKEN: ${{ secrets.node_auth_token }}" in source
    assert source.count("${{ secrets.node_auth_token }}") == 1
    assert not re.search(r"(?m)^\s+GITHUB_TOKEN:", source)
    assert not re.search(r"(?m)^\s+NPM_TOKEN:", source)
    protected_tokens = r"(?:GH_TOKEN|GITHUB_TOKEN|NODE_AUTH_TOKEN|NPM_TOKEN)"
    assert not re.search(rf"(?m)^  {protected_tokens}:", source)
    assert not re.search(rf"(?m)^      {protected_tokens}:", source)
    verifier = _workflow_step_blocks(
        source, "Verify candidate source and signatures with the trusted verifier"
    )
    assert len(verifier) == 1
    assert "GH_TOKEN: ${{ github.token }}" in verifier[0]
    assert "NODE_AUTH_TOKEN: ${{ secrets.node_auth_token }}" in release_preflight[0]

    checkout = f"actions/checkout@{REVIEWED_ACTION_PINS['actions/checkout']}"
    assert source.count(checkout) == 5
    assert source.count("fetch-depth: 0") == 5
    assert source.count("persist-credentials: false") == 5
    assert not re.search(r"(?m)^\s*git\b[^\n]*\bfetch\b", source)
    history_checks = _workflow_step_blocks(
        source, "Establish protected-main history and clean checkouts"
    )
    assert len(history_checks) == 2
    for history_check in history_checks:
        for fragment in (
            "for checkout in trusted candidate; do",
            'test "$(git -C "$checkout" rev-parse --is-shallow-repository)" = "false"',
            'main_commit=$(git -C "$checkout" rev-parse --verify '
            "'refs/remotes/origin/main^{commit}')",
            'test "${#main_commit}" -eq 40',
            'case "$main_commit" in *[!0-9a-f]*) exit 1 ;; esac',
            'test "$(git -C "$checkout" cat-file -t "$main_commit")" = "commit"',
            "status --porcelain --untracked-files=all",
        ):
            assert fragment in history_check
    assert "path: ./.github/actions/" not in source
    assert "path: candidate/.github/actions/" not in source
    assert "trusted/kaji/scripts/verify_ts_handoff_source.py" in source
    assert "trusted/kaji/scripts/ts_handoff.py" in source
    assert "trusted/kaji/scripts/validate_ts_consumer_handoff.py" in source
    assert "candidate/kaji/scripts/" not in source

    stage_command = source.index("trusted/kaji/scripts/ts_handoff.py stage")
    composite = source.index("--for-handoff artifact-contract")
    assert stage_command < composite
    between = source[stage_command:composite]
    assert "uses:" not in between
    assert "npm pack" not in source
    assert "preflight-sha256: ${{ steps.stage.outputs.preflight-sha256 }}" in source
    stage = _workflow_step_blocks(source, "Stage the immutable package exactly once")
    assert len(stage) == 1
    for fragment in (
        "preflight_sha256=$(sha256sum \"$preflight\" | cut -d ' ' -f 1)",
        'test "${#preflight_sha256}" -eq 64',
        'case "$preflight_sha256" in *[!0-9a-f]*) exit 1 ;; esac',
        'test "$stage_preflight_sha256" = "$preflight_sha256"',
        "printf 'preflight-sha256=%s\\n' \"$preflight_sha256\"",
    ):
        assert fragment in stage[0]
    assert re.search(
        r'printf \'preflight-sha256=%s\\n\' "\$preflight_sha256"\n'
        r'\s*\} >>"\$GITHUB_OUTPUT"',
        stage[0],
    )

    authenticate = _workflow_step_blocks(
        source, "Authenticate exact preflight transfer"
    )
    assert len(authenticate) == 1
    for fragment in (
        "EXPECTED_PREFLIGHT_SHA256: ${{ needs.stage.outputs.preflight-sha256 }}",
        'test "${#EXPECTED_PREFLIGHT_SHA256}" -eq 64',
        'case "$EXPECTED_PREFLIGHT_SHA256" in *[!0-9a-f]*) exit 1 ;; esac',
        'test "$(sha256sum "$preflight" | cut -d \' \' -f 1)" = '
        '"$EXPECTED_PREFLIGHT_SHA256"',
        "stage_preflight_sha256=$(jq -er '.preflightSha256 | "
        'select(test("^[0-9a-f]{64}$"))\' "$stage")',
        'test "$stage_preflight_sha256" = "$EXPECTED_PREFLIGHT_SHA256"',
    ):
        assert fragment in authenticate[0]
    finalize = source.index("  finalize:\n")
    authenticate_position = source.index(
        "      - name: Authenticate exact preflight transfer", finalize
    )
    toolchain_position = source.index(
        "      - name: Revalidate transfer and select the recorded toolchain", finalize
    )
    assert authenticate_position < toolchain_position
    for setup_name in (
        "Set up finalizer Python",
        "Set up recorded uv",
        "Set up recorded Node",
        "Set up recorded Bun",
    ):
        assert authenticate_position < source.index(
            f"      - name: {setup_name}", finalize
        )

    stage_upload = _workflow_step_blocks(source, "Upload exact stage transfer envelope")
    assert len(stage_upload) == 1
    assert _literal_paths(stage_upload[0], "path") == [
        ".artifacts/kaji-handoff-staging/",
        ".artifacts/kaji-handoff-inputs/source/",
        ".artifacts/kaji-handoff-inputs/preflight.json",
    ]
    consumer_upload = _workflow_step_blocks(source, "Upload exact consumer handoff")
    attestation = _workflow_step_blocks(source, "Attest exact consumer handoff")
    assert len(consumer_upload) == len(attestation) == 1
    subjects = [
        ".artifacts/kaji-handoff/${{ env.KAJI_HANDOFF_TARBALL }}",
        ".artifacts/kaji-handoff/kaji.manifest.json",
        ".artifacts/kaji-handoff/kaji-ts-consumer-handoff-v1.schema.json",
    ]
    assert _literal_paths(consumer_upload[0], "path") == subjects
    assert _literal_paths(attestation[0], "subject-path") == subjects

    upload_pin = (
        f"actions/upload-artifact@{REVIEWED_ACTION_PINS['actions/upload-artifact']}"
    )
    assert source.count("include-hidden-files: true") == source.count(upload_pin) == 5
    assert source.count("if-no-files-found: error") == 5
    assert "overwrite:" not in source
    assert "merge-multiple:" not in source
    assert not re.search(r"(?m)^          pattern:", source)
    assert "kaji-ts-handoff-node-22-${{ needs.stage.outputs.source-commit }}" in source
    assert "kaji-ts-handoff-node-24-${{ needs.stage.outputs.source-commit }}" in source
    assert "outputs:\n      receipt:" not in source

    retain = _workflow_step_blocks(
        source, "Retain closed transport and provenance evidence"
    )
    assert len(retain) == 1
    for fragment in (
        'case "$KAJI_ATTESTATION_BUNDLE" in /*)',
        'case "$bundle_real" in "$runner_temp_real"/*)',
        "select(length == 1)",
        "(.subject | sort_by(.name)) == ([",
        'apiDigest: ("sha256:" + $actionDigest)',
        'attestations/" + $attestationId',
        "expected_evidence",
        "expected_receipt_set",
    ):
        assert fragment in retain[0]
    assert "acceptedHandoff: true" not in source
    assert '"acceptedHandoff":true' not in source


def test_trusted_handoff_workflow_has_closed_transport_and_trust_boundaries() -> None:
    source = (REPO_ROOT / ".github/workflows/kaji.handoff.trusted.yml").read_text()
    _assert_trusted_handoff_workflow_source(source)


@pytest.mark.parametrize(
    "before,after",
    [
        ("${{ job.workflow_repository }}", "${{ github.repository }}"),
        ("GH_TOKEN: ${{ github.token }}", "GH_TOKEN: ${{ secrets.node_auth_token }}"),
        ("include-hidden-files: true", "include-hidden-files: false"),
        (
            "            .artifacts/kaji-handoff-staging/\n"
            "            .artifacts/kaji-handoff-inputs/source/",
            "            .artifacts/kaji-handoff-staging/**\n"
            "            .artifacts/kaji-handoff-inputs/source/",
        ),
        ("select(length == 1)", "select(length >= 1)"),
        (
            "secrets:\n      node_auth_token:",
            "secrets: inherit\n      node_auth_token:",
        ),
        (
            "permissions:\n  contents: read\n",
            "permissions:\n  contents: read\n\nenv:\n  GH_TOKEN: ${{ github.token }}\n",
        ),
        (
            "  stage:\n    name: trusted source, stage, and artifact contract\n",
            "  stage:\n    name: trusted source, stage, and artifact contract\n"
            "    env:\n      NODE_AUTH_TOKEN: ${{ secrets.node_auth_token }}\n",
        ),
        (
            "preflight-sha256: ${{ steps.stage.outputs.preflight-sha256 }}",
            "preflight-sha256: ${{ steps.stage.outputs.artifact-sha256 }}",
        ),
        (
            "EXPECTED_PREFLIGHT_SHA256: ${{ needs.stage.outputs.preflight-sha256 }}",
            "EXPECTED_PREFLIGHT_SHA256: ${{ needs.stage.outputs.artifact-sha256 }}",
        ),
        (
            "          GH_TOKEN: ${{ github.token }}",
            "          GH_TOKEN: ${{ github.token }}\n"
            "          SAFE_ALIAS: ${{ github.token }}",
        ),
        (
            "          NODE_AUTH_TOKEN: ${{ secrets.node_auth_token }}",
            "          NODE_AUTH_TOKEN: ${{ secrets.node_auth_token }}\n"
            "          SAFE_ALIAS: ${{ secrets.node_auth_token }}",
        ),
        (
            "      - name: Independently validate exact consumer handoff\n"
            "        shell: bash\n",
            "      - name: Independently validate exact consumer handoff\n"
            "        continue-on-error: true\n"
            "        shell: bash\n",
        ),
        (
            "      - name: Independently validate exact consumer handoff\n"
            "        shell: bash\n",
            "      - name: Independently validate exact consumer handoff\n"
            "        if: ${{ always() }}\n"
            "        shell: bash\n",
        ),
        (
            "  finalize:\n    name: finalize and attest consumer handoff\n",
            "  finalize:\n    name: finalize and attest consumer handoff\n"
            "    if: ${{ always() }}\n",
        ),
        (
            "if: ${{ inputs.mode == 'release' }}",
            "if: ${{ always() }}",
        ),
        (
            "persist-credentials: false",
            "persist-credentials: true",
        ),
        (
            "fetch-depth: 0",
            "fetch-depth: 1",
        ),
        (
            "refs/remotes/origin/main^{commit}",
            "refs/heads/main^{commit}",
        ),
        (
            '            test "${#main_commit}" -eq 40\n',
            '            git -C "$checkout" fetch origin main\n'
            '            test "${#main_commit}" -eq 40\n',
        ),
    ],
)
def test_trusted_handoff_workflow_rejects_security_mutations(
    before: str, after: str
) -> None:
    source = (REPO_ROOT / ".github/workflows/kaji.handoff.trusted.yml").read_text()
    assert before in source
    mutated = source.replace(before, after, 1)
    with pytest.raises(AssertionError):
        _assert_trusted_handoff_workflow_source(mutated)
