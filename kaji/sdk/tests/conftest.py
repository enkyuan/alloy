from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from typing import NoReturn

import httpx
import pytest


_OFFLINE_ERROR = "KAJI offline gate blocked network access"


def _blocked(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError(_OFFLINE_ERROR)


async def _blocked_async(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError(_OFFLINE_ERROR)


@pytest.fixture(autouse=True)
def _offline_network_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if os.environ.get("KAJI_OFFLINE_GATE") != "1":
        yield
        return

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket, "gethostbyname", _blocked)
    monkeypatch.setattr(socket, "gethostbyname_ex", _blocked)
    monkeypatch.setattr(socket, "getnameinfo", _blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", _blocked_async
    )
    yield
