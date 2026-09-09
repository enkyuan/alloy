from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import socket
from collections.abc import Iterator
from typing import NoReturn

import httpx
import pytest


_OFFLINE_ERROR = "KAJI offline gate blocked network access"
_SOURCE_INIT = Path(__file__).resolve().parents[1] / "src" / "__init__.py"


def _load_source_package() -> None:
    spec = importlib.util.spec_from_file_location("kaji", _SOURCE_INIT)
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules["kaji"] = package
    spec.loader.exec_module(package)


_load_source_package()


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
