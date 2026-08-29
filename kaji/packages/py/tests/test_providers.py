import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import call, patch

import httpx
import pytest

from kaji.core.config import settings
from kaji.runtime.providers.errors import (
    ProviderAPIError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderRateLimitedError,
)
from kaji.runtime.providers.kimi import KimiProvider
from kaji.runtime.providers.registry import get_provider


@pytest.mark.asyncio
async def test_provider_registry_selects_kimi_explicitly():
    with (
        patch("kaji.core.config.settings.KAJI_MODEL_PROVIDER", "kimi"),
        patch("kaji.core.config.settings.OPENROUTER_API_KEY", "test_key"),
    ):
        provider = get_provider("kimi")
        assert isinstance(provider, KimiProvider)


def test_missing_provider_config_fails_clearly():
    with pytest.raises(ProviderConfigError, match="not registered"):
        get_provider("nonexistent")


def test_kimi_provider_honors_explicit_options():
    provider = KimiProvider(
        api_key="explicit-key",
        model="explicit-model",
        base_url="https://example.test/chat/completions",
        http_referer="https://app.test",
        app_title="Example App",
    )

    assert provider.api_key == "explicit-key"
    assert provider.model_name == "explicit-model"
    assert provider.base_url == "https://example.test/chat/completions"
    assert provider._get_headers()["HTTP-Referer"] == "https://app.test"
    assert provider._get_headers()["X-OpenRouter-Title"] == "Example App"


def test_kimi_provider_rejects_unknown_options():
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        cast(Any, KimiProvider)(api_key="explicit-key", retired_option=True)


def test_kimi_provider_requires_current_credentials():
    with (
        patch("kaji.core.config.settings.OPENROUTER_API_KEY", None),
        patch("kaji.core.config.settings.CLOUDFLARE_ACCOUNT_ID", None),
        patch("kaji.core.config.settings.CLOUDFLARE_API_TOKEN", None),
    ):
        with pytest.raises(ProviderConfigError, match="OPENROUTER_API_KEY"):
            KimiProvider()


def test_mock_provider_does_not_eager_import_optional_provider_modules():
    for module in [
        "kaji.runtime.providers.anthropic",
        "kaji.runtime.providers.gemini",
        "kaji.runtime.providers.openai",
    ]:
        sys.modules.pop(module, None)

    provider = get_provider("mock")

    assert provider.__class__.__name__ == "MockProvider"
    assert "kaji.runtime.providers.anthropic" not in sys.modules
    assert "kaji.runtime.providers.gemini" not in sys.modules
    assert "kaji.runtime.providers.openai" not in sys.modules


@pytest.mark.asyncio
async def test_kimi_provider_normalizes_request_payload():
    with (
        patch("kaji.core.config.settings.OPENROUTER_API_KEY", "test_key"),
        patch("kaji.core.config.settings.CLOUDFLARE_ACCOUNT_ID", None),
    ):
        provider = KimiProvider()

        messages = [{"role": "user", "content": "hello"}]
        payload = provider._prepare_payload(
            messages=messages, system_instruction="Be helpful"
        )

        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "Be helpful"
        assert payload["messages"][1]["role"] == "user"
        assert payload["messages"][1]["content"] == "hello"
        assert payload["model"] == settings.KIMI_MODEL


@pytest.mark.asyncio
async def test_kimi_provider_normalizes_mocked_streaming_response():
    with patch("kaji.core.config.settings.OPENROUTER_API_KEY", "test_key"):
        provider = KimiProvider()

        # Mock httpx.AsyncClient.stream
        class MockResponse:
            status_code = 200

            async def aiter_lines(self):
                # Simulated SSE stream
                yield 'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}'
                yield 'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClient:
            def stream(self, *args, **kwargs):
                return MockResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("httpx.AsyncClient", return_value=MockClient()):
            chunks = []
            async for chunk in provider.generate_stream(messages=[]):
                chunks.append(chunk.delta)

            assert chunks == ["Hello", " world"]


@pytest.mark.asyncio
async def test_kimi_provider_maps_rate_limits_to_service_error():
    provider = KimiProvider(api_key="test_key")

    class MockResponse:
        status_code = 429
        text = "slow down"

    class MockClient:
        async def post(self, *args, **kwargs):
            return MockResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("httpx.AsyncClient", return_value=MockClient()):
        with pytest.raises(ProviderRateLimitedError):
            await provider.generate(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_provider_maps_transport_errors_to_network_error():
    provider = KimiProvider(api_key="test_key")

    class MockClient:
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("connection failed")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("httpx.AsyncClient", return_value=MockClient()):
        with pytest.raises(ProviderConnectionError):
            await provider.generate(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_provider_rejects_invalid_json_response():
    provider = KimiProvider(api_key="test_key")

    class MockResponse:
        status_code = 200
        text = "not json"

        def json(self):
            raise ValueError("bad json")

    class MockClient:
        async def post(self, *args, **kwargs):
            return MockResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("httpx.AsyncClient", return_value=MockClient()):
        with pytest.raises(ProviderAPIError):
            await provider.generate(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_provider_accumulates_fragmented_streaming_tool_calls():
    with patch("kaji.core.config.settings.OPENROUTER_API_KEY", "test_key"):
        provider = KimiProvider()

        class MockResponse:
            status_code = 200

            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"lookup","arguments":"{\\"q\\":"}}]}}]}'
                yield 'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"type":"function","function":{"arguments":"\\"weather\\"}"}}]}}]}'
                yield "data: [DONE]"

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClient:
            def stream(self, *args, **kwargs):
                return MockResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("httpx.AsyncClient", return_value=MockClient()):
            chunks = [chunk async for chunk in provider.generate_stream(messages=[])]

    assert len(chunks) == 1
    assert chunks[0].delta == ""
    assert chunks[0].tool_calls == [
        {"id": "call-1", "name": "lookup", "arguments": {"q": "weather"}}
    ]


def test_gemini_provider_remains_loadable():
    # Should not throw ImportError
    from kaji.runtime.providers.gemini import GeminiProvider

    assert GeminiProvider is not None


def test_gemini_provider_uses_explicit_service():
    from kaji.runtime.providers import gemini

    service = object.__new__(gemini.GeminiService)
    service.model = "gemini-test"
    provider = gemini.GeminiProvider(service=service)

    assert provider.service is service


def test_gemini_provider_owns_service_by_default():
    from kaji.runtime.providers import gemini

    first_service = SimpleNamespace(model="gemini-first")
    second_service = SimpleNamespace(model="gemini-second")
    with patch.object(
        gemini,
        "GeminiService",
        side_effect=[first_service, second_service],
    ) as service_type:
        first = gemini.GeminiProvider()
        second = gemini.GeminiProvider()

    assert first.service is first_service
    assert second.service is second_service
    assert service_type.call_args_list == [call(api_key=None), call(api_key=None)]


def test_gemini_provider_rejects_ambiguous_service_configuration():
    from kaji.runtime.providers.gemini import GeminiProvider, GeminiService

    with pytest.raises(ValueError, match="mutually exclusive"):
        GeminiProvider(api_key="explicit", service=object.__new__(GeminiService))


def test_gemini_service_uses_explicit_api_key():
    from kaji.runtime.providers.gemini import GeminiService

    captured = {}

    class Client:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = SimpleNamespace()

    genai = SimpleNamespace(Client=Client)

    with patch("kaji.runtime.providers.gemini.import_module", return_value=genai):
        service = GeminiService(api_key="explicit-gemini-key")

    assert service.api_key == "explicit-gemini-key"
    assert captured["api_key"] == "explicit-gemini-key"


def test_gemini_service_missing_key_raises_provider_config_error():
    from kaji.runtime.providers.gemini import GeminiService

    with patch("kaji.runtime.providers.gemini.get_settings") as mock_settings:
        mock_settings.return_value.GEMINI_API_KEY = None
        with pytest.raises(ProviderConfigError):
            GeminiService()


@pytest.mark.asyncio
async def test_gemini_service_uses_configured_embedding_model():
    from kaji.runtime.providers.gemini import GeminiService

    captured = {}

    class Models:
        def embed_content(self, *, model, contents):
            captured["model"] = model
            captured["contents"] = contents
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.25, -0.5])])

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    genai = SimpleNamespace(Client=Client)
    configured_settings = SimpleNamespace(
        GEMINI_API_KEY=None,
        GEMINI_MODEL="gemini-chat-test",
        GEMINI_EMBEDDING_MODEL="gemini-embedding-test",
    )

    with (
        patch(
            "kaji.runtime.providers.gemini.get_settings",
            return_value=configured_settings,
        ),
        patch("kaji.runtime.providers.gemini.import_module", return_value=genai),
    ):
        service = GeminiService(api_key="explicit-gemini-key")
        embedding = await service.embed_text("hello")

    assert service.model == "gemini-chat-test"
    assert captured == {"model": "gemini-embedding-test", "contents": "hello"}
    assert embedding == [0.25, -0.5]


@pytest.mark.asyncio
async def test_gemini_service_applies_chat_output_limits():
    from kaji.runtime.providers.gemini import GeminiService

    configs = []

    class Models:
        def generate_content(self, *, model, contents, config):
            configs.append(config)
            return SimpleNamespace(text="ok")

        def generate_content_stream(self, *, model, contents, config):
            configs.append(config)
            return iter(())

    service = object.__new__(GeminiService)
    service.client = cast(Any, SimpleNamespace(models=Models()))
    service.model = "gemini-test"
    service._active_caches = {}

    await service.generate_chat_response(
        [{"role": "user", "content": "hello"}],
        max_tokens=123,
    )
    _ = [
        chunk
        async for chunk in service.generate_chat_stream(
            [{"role": "user", "content": "hello"}],
            max_tokens=456,
        )
    ]

    assert configs == [
        {"temperature": 0.7, "max_output_tokens": 123},
        {"temperature": 0.7, "max_output_tokens": 456},
    ]


@pytest.mark.asyncio
async def test_gemini_context_cache_is_owned_by_service_instance():
    from kaji.runtime.providers.gemini import GeminiService

    created_for = []

    class Models:
        def count_tokens(self, *, model, contents):
            return SimpleNamespace(total_tokens=40_000)

    class Caches:
        def create(self, *, model, config):
            created_for.append(model)
            return SimpleNamespace(name=f"cache-{model}")

    contents = [{"role": "user", "parts": [str(index)]} for index in range(3)]
    client = SimpleNamespace(models=Models(), caches=Caches())
    first = object.__new__(GeminiService)
    first.client = cast(Any, client)
    first.model = "gemini-first"
    first._active_caches = {}
    second = object.__new__(GeminiService)
    second.client = cast(Any, client)
    second.model = "gemini-second"
    second._active_caches = {}

    assert await first._get_active_cache("system", contents, None) == (
        "cache-gemini-first"
    )
    assert await second._get_active_cache("system", contents, None) == (
        "cache-gemini-second"
    )
    assert created_for == ["gemini-first", "gemini-second"]


@pytest.mark.asyncio
async def test_gemini_context_cache_recreates_before_remote_expiry():
    from kaji.runtime.providers.gemini import GeminiService

    created = []

    class Models:
        def count_tokens(self, *, model, contents):
            return SimpleNamespace(total_tokens=40_000)

    class Caches:
        def create(self, *, model, config):
            name = f"cache-{len(created) + 1}"
            created.append(name)
            return SimpleNamespace(name=name)

    contents = [{"role": "user", "parts": [str(index)]} for index in range(3)]
    service = object.__new__(GeminiService)
    service.client = cast(Any, SimpleNamespace(models=Models(), caches=Caches()))
    service.model = "gemini-test"
    service._active_caches = {}

    with patch(
        "kaji.runtime.providers.gemini.monotonic",
        side_effect=[0.0, 539.0, 541.0, 541.0],
    ):
        assert await service._get_active_cache("system", contents, None) == "cache-1"
        assert await service._get_active_cache("system", contents, None) == "cache-1"
        assert await service._get_active_cache("system", contents, None) == "cache-2"

    assert created == ["cache-1", "cache-2"]


@pytest.mark.asyncio
async def test_gemini_service_maps_status_errors_to_service_error():
    from kaji.runtime.providers.gemini import GeminiService

    class RateLimitError(Exception):
        status_code = 429

    class Models:
        def generate_content(self, *args, **kwargs):
            raise RateLimitError("slow down")

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    genai = SimpleNamespace(Client=Client)

    with patch("kaji.runtime.providers.gemini.import_module", return_value=genai):
        service = GeminiService(api_key="explicit-gemini-key")

    with pytest.raises(ProviderRateLimitedError):
        await service.generate_response("hello")


def test_runtime_does_not_import_provider_specific_implementation():
    import ast

    from kaji.runtime.agents import runtime

    with open(runtime.__file__, "r") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "gemini" not in alias.name
                assert "kimi" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "gemini" not in node.module
                assert "kimi" not in node.module
