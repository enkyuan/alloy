from __future__ import annotations

import os
import socket

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("KAJI_OFFLINE_GATE") != "1",
    reason="offline guard self-tests run through offline_gate.py",
)


@pytest.mark.parametrize(
    ("operation_name", "arguments"),
    [
        ("create_connection", (("127.0.0.1", 9),)),
        ("getaddrinfo", ("example.invalid", 443)),
        ("gethostbyname", ("example.invalid",)),
        ("gethostbyname_ex", ("example.invalid",)),
        ("getnameinfo", (("127.0.0.1", 9), 0)),
    ],
)
def test_offline_guard_blocks_socket_and_dns_before_io(
    operation_name: str, arguments: tuple[object, ...]
) -> None:
    operation = getattr(socket, operation_name)
    with pytest.raises(
        RuntimeError, match="^KAJI offline gate blocked network access$"
    ):
        operation(*arguments)  # type: ignore[operator]


def test_offline_guard_blocks_socket_connect_methods() -> None:
    direct = socket.socket()
    try:
        with pytest.raises(
            RuntimeError, match="^KAJI offline gate blocked network access$"
        ):
            direct.connect(("127.0.0.1", 9))
        with pytest.raises(
            RuntimeError, match="^KAJI offline gate blocked network access$"
        ):
            direct.connect_ex(("127.0.0.1", 9))
    finally:
        direct.close()


def test_offline_guard_blocks_default_httpx_transports() -> None:
    with httpx.Client() as client:
        with pytest.raises(
            RuntimeError, match="^KAJI offline gate blocked network access$"
        ):
            client.get("https://example.invalid/")


async def test_offline_guard_blocks_default_async_httpx_transport() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(
            RuntimeError, match="^KAJI offline gate blocked network access$"
        ):
            await client.get("https://example.invalid/")


def test_offline_guard_allows_injected_httpx_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = client.get("https://example.invalid/")
    assert response.content == b"offline"
