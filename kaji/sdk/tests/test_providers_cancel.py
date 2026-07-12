"""Symmetric cancellation across all providers.

Both ``generate()`` and ``generate_stream()`` must raise ``CancelledError`` when
the cancellation token is set, so callers observe cancellation uniformly. The
previous ``generate_stream()`` implementations silently ``break``'d mid-stream,
returning partial responses that looked like clean exits.

Each provider needs its own fake-client wiring (Kimi: httpx SSE, OpenAI: lazy
client property, Anthropic: async-context stream, Gemini: service shim), so the
provider factories live in ``_PROVIDERS``. The four behavioral assertions are
parametrized across all of them — new providers add one entry here and inherit
the full cancel contract.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import pytest

from kaji.runtime.agents.cancellation import CancellationToken


# ---------------------------------------------------------------------------
# Per-provider fakes + factory
# ---------------------------------------------------------------------------


# --- Kimi -------------------------------------------------------------------


class _KimiStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):  # pragma: no cover - error path not exercised here
        return b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class _KimiStreamClient:
    def __init__(self, lines):
        self._lines = lines

    def stream(self, *_args, **_kwargs):
        return _KimiStreamResponse(self._lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _make_kimi(chunks: list[str] | None):
    from kaji.runtime.providers.kimi import KimiProvider

    with (
        patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"),
        patch("kaji.core.config.settings.CLOUDFLARE_ACCOUNT_ID", None),
    ):
        provider = KimiProvider()

    if chunks is None:
        return provider, lambda: None

    lines = [
        f'data: {{"choices":[{{"delta":{{"content":"{c}"}}}}]}}' for c in chunks
    ] + ["data: [DONE]"]
    patcher = patch("httpx.AsyncClient", return_value=_KimiStreamClient(lines))
    patcher.start()
    return provider, patcher.stop


# --- OpenAI -----------------------------------------------------------------


def _openai_chunk(content: str):
    return type(
        "C",
        (),
        {
            "choices": [
                type(
                    "Ch",
                    (),
                    {"delta": type("D", (), {"content": content, "tool_calls": None})},
                )()
            ]
        },
    )()


def _make_openai(chunks: list[str] | None):
    from kaji.runtime.providers.openai import OpenAIProvider

    provider = OpenAIProvider(model="gpt-4o-mini", api_key="dummy")

    async def _fake_stream():
        for c in chunks or []:
            yield _openai_chunk(c)

    class _FakeCompletions:
        async def create(self, **_kw):
            return _fake_stream()

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    provider._client = _FakeClient()
    return provider, lambda: None


# --- Anthropic --------------------------------------------------------------


def _anthropic_event(text: str):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


class _AnthropicStream:
    def __init__(self, events):
        self._events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()


class _AnthropicMessages:
    def __init__(self, events):
        self._events = events
        self._response = SimpleNamespace(
            content=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0)
        )

    async def create(self, **_kw):
        return self._response

    def stream(self, **_kw):
        return _AnthropicStream(self._events)


def _make_anthropic(chunks: list[str] | None):
    from kaji.runtime.providers.anthropic import AnthropicProvider

    events = [_anthropic_event(c) for c in chunks or []]

    with patch("kaji.core.config.settings.ANTHROPIC_API_KEY", "test_key"):
        provider = AnthropicProvider()
    provider._client = SimpleNamespace(messages=_AnthropicMessages(events))
    return provider, lambda: None


# --- Gemini -----------------------------------------------------------------


def _gemini_chunk(text: str):
    return SimpleNamespace(text=text, candidates=[])


class _GeminiService:
    model = "gemini-test"

    def __init__(self, chunks):
        self._chunks = chunks

    async def generate_chat_response(self, *_a, **_kw):
        return SimpleNamespace(text="ok", candidates=[], usage_metadata=None)

    async def generate_chat_stream(self, *_a, **_kw):
        for chunk in self._chunks:
            yield chunk


def _make_gemini(chunks: list[str] | None):
    service = _GeminiService([_gemini_chunk(c) for c in chunks or []])
    with patch(
        "kaji.runtime.providers.gemini.get_gemini_service", return_value=service
    ):
        from kaji.runtime.providers.gemini import GeminiProvider

        return GeminiProvider(), lambda: None


# --- Registry ---------------------------------------------------------------


_PROVIDERS: dict[str, Callable[[list[str] | None], tuple[Any, Callable[[], None]]]] = {
    "kimi": _make_kimi,
    "openai": _make_openai,
    "anthropic": _make_anthropic,
    "gemini": _make_gemini,
}


@pytest.mark.parametrize(
    ("module_name", "provider_name", "client_name"),
    [
        ("kaji.runtime.providers.openai", "OpenAIProvider", "AsyncOpenAI"),
        ("kaji.runtime.providers.anthropic", "AnthropicProvider", "AsyncAnthropic"),
    ],
)
def test_provider_request_timeout_is_forwarded_to_vendor_client(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    provider_name: str,
    client_name: str,
) -> None:
    module = __import__(module_name, fromlist=[provider_name])
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        module,
        "import_module",
        lambda _name: SimpleNamespace(**{client_name: client}),
    )
    provider = getattr(module, provider_name)(
        api_key="configured",
        request_timeout_seconds=12.5,
    )

    assert provider.client is not None
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 12.5


@pytest.mark.parametrize(
    ("module_name", "provider_name", "client_name"),
    [
        ("kaji.runtime.providers.openai", "OpenAIProvider", "AsyncOpenAI"),
        ("kaji.runtime.providers.anthropic", "AnthropicProvider", "AsyncAnthropic"),
    ],
)
def test_provider_request_timeout_is_omitted_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    provider_name: str,
    client_name: str,
) -> None:
    module = __import__(module_name, fromlist=[provider_name])
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        module,
        "import_module",
        lambda _name: SimpleNamespace(**{client_name: client}),
    )
    provider = getattr(module, provider_name)(api_key="configured")

    assert provider.client is not None
    assert captured["max_retries"] == 0
    assert "timeout" not in captured


@pytest.mark.parametrize(
    ("provider_name", "value", "error_type"),
    [
        ("OpenAIProvider", True, TypeError),
        ("OpenAIProvider", "1", TypeError),
        ("OpenAIProvider", 0, ValueError),
        ("OpenAIProvider", -1, ValueError),
        ("OpenAIProvider", float("nan"), ValueError),
        ("OpenAIProvider", float("inf"), ValueError),
        ("AnthropicProvider", True, TypeError),
        ("AnthropicProvider", "1", TypeError),
        ("AnthropicProvider", 0, ValueError),
        ("AnthropicProvider", -1, ValueError),
        ("AnthropicProvider", float("nan"), ValueError),
        ("AnthropicProvider", float("inf"), ValueError),
    ],
)
def test_provider_request_timeout_rejects_invalid_values(
    provider_name: str,
    value: object,
    error_type: type[Exception],
) -> None:
    module_name = provider_name.removesuffix("Provider").lower()
    module = __import__(
        f"kaji.runtime.providers.{module_name}", fromlist=[provider_name]
    )

    with pytest.raises(error_type, match="request_timeout_seconds"):
        getattr(module, provider_name)(
            api_key="configured",
            request_timeout_seconds=value,
        )


@pytest.fixture(params=list(_PROVIDERS.keys()))
def provider_factory(request):
    """Yields a factory ``(chunks) -> (provider, cleanup)`` for one provider.

    The factory takes a list of streaming chunk strings (or ``None`` when only
    ``generate()`` is exercised) and returns the wired provider plus a cleanup
    callable to undo any patches.
    """
    return _PROVIDERS[request.param]


# ---------------------------------------------------------------------------
# Behavioral tests — run against every provider
# ---------------------------------------------------------------------------


async def test_generate_raises_when_token_already_cancelled(provider_factory):
    provider, cleanup = provider_factory(None)
    try:
        token = CancellationToken()
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await provider.generate(
                messages=[{"role": "user", "content": "hi"}],
                cancellation_token=token,
            )
    finally:
        cleanup()


async def test_generate_stream_raises_when_token_already_cancelled(provider_factory):
    provider, cleanup = provider_factory(["never"])
    try:
        token = CancellationToken()
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            async for _ in provider.generate_stream(
                messages=[{"role": "user", "content": "hi"}],
                cancellation_token=token,
            ):
                pass
    finally:
        cleanup()


async def test_generate_stream_raises_mid_stream_on_cancel(provider_factory):
    """Cancellation observed mid-stream must raise, not silently break-exit."""
    provider, cleanup = provider_factory(["hello ", "world", "!"])
    try:
        token = CancellationToken()

        async def consume():
            chunks = []
            async for chunk in provider.generate_stream(
                messages=[{"role": "user", "content": "hi"}],
                cancellation_token=token,
            ):
                chunks.append(chunk)
                token.cancel()
            return chunks

        with pytest.raises(asyncio.CancelledError):
            await consume()
    finally:
        cleanup()


async def test_generate_stream_completes_when_token_never_set(provider_factory):
    provider, cleanup = provider_factory(["ok"])
    try:
        token = CancellationToken()

        chunks = []
        async for chunk in provider.generate_stream(
            messages=[{"role": "user", "content": "hi"}],
            cancellation_token=token,
        ):
            chunks.append(chunk)

        assert any(c.delta == "ok" for c in chunks)
    finally:
        cleanup()
