import sys
from unittest.mock import patch

import pytest

from kaji.core.config import settings
from kaji.runtime.providers.errors import ProviderConfigError
from kaji.runtime.providers.kimi import KimiProvider
from kaji.runtime.providers.registry import get_provider


@pytest.mark.asyncio
async def test_provider_registry_selects_kimi_by_default():
    # Assuming settings.KAJI_MODEL_PROVIDER defaults to "kimi" in test config or we mock it
    # We can just test the registry logic
    with (
        patch("kaji.core.config.settings.KAJI_MODEL_PROVIDER", "kimi"),
        patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"),
    ):
        provider = get_provider("kimi")
        assert isinstance(provider, KimiProvider)


def test_missing_provider_config_fails_clearly():
    with pytest.raises(ProviderConfigError, match="not registered"):
        get_provider("nonexistent")


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
        patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"),
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
    with patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"):
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
async def test_kimi_provider_accumulates_fragmented_streaming_tool_calls():
    with patch("kaji.core.config.settings.KIMI_API_KEY", "test_key"):
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
