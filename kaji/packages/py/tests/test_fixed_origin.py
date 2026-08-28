from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time

import httpx
import pytest

from kaji.integrations.errors import (
    IntegrationPolicyError,
    IntegrationTransportError,
)
from kaji.integrations.fixed_origin import FixedOriginClient
from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools.execution import ToolExecutionError


def context(
    *,
    token: CancellationToken | None = None,
    deadline_monotonic: float | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id="tester",
        session_id="session",
        turn_id="turn",
        request_id="request",
        trace_id="trace",
        tool_call_id="call",
        idempotency_key="session:call",
        cancellation_token=token or CancellationToken(),
        deadline_monotonic=deadline_monotonic,
        db=None,
        metadata={},
    )


def client(
    handler,
    *,
    origin: str = "https://api.github.com",
    timeout_seconds: float = 1.0,
    max_response_bytes: int = 32,
) -> FixedOriginClient:
    return FixedOriginClient._for_test(
        origin,
        transport=httpx.MockTransport(handler),
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "",
        "https://evil.example/x",
        "//evil.example/x",
        "\\\\evil.example\\x",
        "/x#secret",
        "/%2f%2fevil.example/x",
        "/%5cevil.example/x",
    ],
)
async def test_rejects_unsafe_paths_before_transport(path: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"unused")

    http = client(handler)
    with pytest.raises(IntegrationPolicyError):
        await http.request(
            path,
            method="GET",
            headers={},
            body=None,
            context=context(),
        )
    assert calls == 0
    await http.aclose()


@pytest.mark.asyncio
async def test_keeps_url_looking_query_data_on_fixed_origin() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, headers={"X-Test": "ok"}, content=b"body")

    http = client(handler)
    response = await http.request(
        "/search/code?q=https%3A%2F%2Fevil.example",
        method="GET",
        headers={"Accept": "application/json"},
        body=None,
        context=context(),
    )

    assert requested == [
        "https://api.github.com/search/code?q=https%3A%2F%2Fevil.example"
    ]
    assert response.status == 200
    assert response.headers == {"x-test": "ok", "content-length": "4"}
    assert response.body == b"body"
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Content-Length": "1"},
        {"Connection": "close"},
        {"Proxy-Authorization": "secret"},
    ],
)
async def test_rejects_authority_and_framing_headers_before_transport(
    headers: dict[str, str],
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    http = client(handler)
    with pytest.raises(IntegrationPolicyError):
        await http.request(
            "/x", method="GET", headers=headers, body=None, context=context()
        )
    assert calls == 0
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["/next", "https://evil.example/next"])
async def test_rejects_every_redirect_as_non_certified_transport_error(
    location: str,
) -> None:
    http = client(lambda _request: httpx.Response(302, headers={"Location": location}))

    with pytest.raises(IntegrationTransportError) as caught:
        await http.request(
            "/start", method="POST", headers={}, body=b"payload", context=context()
        )

    assert caught.value.error_code == "INTEGRATION_REDIRECT_REJECTED"
    assert not isinstance(caught.value, ToolExecutionError)
    assert location not in str(caught.value)
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Length": "not-a-number"},
        {"Content-Length": "33"},
        {f"X-{index}": "v" for index in range(65)},
        {"X-Large": "x" * (64 * 1024)},
    ],
)
async def test_rejects_malformed_or_oversized_response_headers(
    headers: dict[str, str],
) -> None:
    http = client(lambda _request: httpx.Response(200, headers=headers, content=b""))
    with pytest.raises(IntegrationTransportError) as caught:
        await http.request("/x", method="GET", headers={}, body=None, context=context())
    assert caught.value.error_code == "INTEGRATION_RESPONSE_LIMIT"
    await http.aclose()


@pytest.mark.asyncio
async def test_streams_only_to_one_byte_over_body_limit() -> None:
    http = client(
        lambda _request: httpx.Response(
            200,
            stream=ChunkStream(),
        )
    )
    with pytest.raises(IntegrationTransportError) as caught:
        await http.request("/x", method="GET", headers={}, body=None, context=context())
    assert caught.value.error_code == "INTEGRATION_RESPONSE_LIMIT"
    await http.aclose()


class NeverStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        await asyncio.Event().wait()
        yield b"unreachable"

    async def aclose(self) -> None:
        self.closed = True


class ChunkStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"a" * 16
        yield b"b" * 17

    async def aclose(self) -> None:
        return


@pytest.mark.asyncio
async def test_timeout_closes_a_response_stream_that_never_finishes() -> None:
    stream = NeverStream()
    http = client(
        lambda _request: httpx.Response(200, stream=stream),
        timeout_seconds=0.01,
    )
    with pytest.raises(TimeoutError, match="Integration request timed out"):
        await http.request("/x", method="GET", headers={}, body=None, context=context())
    assert stream.closed
    await http.aclose()


@pytest.mark.asyncio
async def test_context_cancellation_closes_pending_response() -> None:
    stream = NeverStream()
    entered = asyncio.Event()

    def handler(_request: httpx.Request) -> httpx.Response:
        entered.set()
        return httpx.Response(200, stream=stream)

    token = CancellationToken()
    http = client(handler)
    pending = asyncio.create_task(
        http.request(
            "/x", method="GET", headers={}, body=None, context=context(token=token)
        )
    )
    await entered.wait()
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream.closed
    await http.aclose()


@pytest.mark.asyncio
async def test_context_deadline_tightens_policy_timeout() -> None:
    stream = NeverStream()
    http = client(
        lambda _request: httpx.Response(200, stream=stream),
        timeout_seconds=10,
    )
    with pytest.raises(TimeoutError, match="Integration request timed out"):
        await http.request(
            "/x",
            method="GET",
            headers={},
            body=None,
            context=context(deadline_monotonic=time.monotonic() + 0.01),
        )
    assert stream.closed
    await http.aclose()


@pytest.mark.asyncio
async def test_httpx_client_disables_ambient_proxy_configuration(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    http = client(lambda _request: httpx.Response(200, content=b"ok"))

    assert http._client._trust_env is False
    assert (
        await http.request("/x", method="GET", headers={}, body=None, context=context())
    ).body == b"ok"
    await http.aclose()


def test_production_factories_are_provider_fixed() -> None:
    github = FixedOriginClient.for_github()
    gmail = FixedOriginClient.for_gmail()
    assert github._origin == "https://api.github.com"
    assert gmail._origin == "https://gmail.googleapis.com"
