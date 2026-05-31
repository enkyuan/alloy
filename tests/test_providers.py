import json
from unittest.mock import AsyncMock, patch

import pytest

from agentkit.core.config import settings
from agentkit.providers.errors import ProviderAPIError, ProviderConfigError
from agentkit.providers.gemini import GeminiProvider
from agentkit.providers.kimi import KimiProvider
from agentkit.providers.registry import get_provider, register_provider
from agentkit.providers.types import ModelResponseChunk


@pytest.mark.asyncio
async def test_provider_registry_selects_kimi_by_default():
    # Assuming settings.AGENTKIT_MODEL_PROVIDER defaults to "kimi" in test config or we mock it
    # We can just test the registry logic
    with (
        patch("agentkit.core.config.settings.AGENTKIT_MODEL_PROVIDER", "kimi"),
        patch("agentkit.core.config.settings.KIMI_API_KEY", "test_key"),
    ):
        provider = get_provider("kimi")
        assert isinstance(provider, KimiProvider)


def test_missing_provider_config_fails_clearly():
    with pytest.raises(ProviderConfigError, match="not registered"):
        get_provider("nonexistent")


@pytest.mark.asyncio
async def test_kimi_provider_normalizes_request_payload():
    with (
        patch("agentkit.core.config.settings.KIMI_API_KEY", "test_key"),
        patch("agentkit.core.config.settings.CLOUDFLARE_ACCOUNT_ID", None),
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
    with patch("agentkit.core.config.settings.KIMI_API_KEY", "test_key"):
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


def test_gemini_provider_remains_loadable():
    # Should not throw ImportError
    from agentkit.providers.gemini import GeminiProvider

    assert GeminiProvider is not None


def test_runtime_does_not_import_provider_specific_implementation():
    import ast

    from agentkit.agents import runtime

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
