import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agentkit.runtime.providers.errors import ProviderConfigError
from agentkit.runtime.providers.registry import get_provider


def test_openai_provider_registered_and_loadable():
    from agentkit.runtime.providers.openai import OpenAIProvider

    assert OpenAIProvider is not None


def test_openai_provider_requires_api_key():
    with patch("agentkit.core.config.settings.OPENAI_API_KEY", None):
        with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
            get_provider("openai")


def test_openai_provider_builds_messages_with_system():
    with patch("agentkit.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = get_provider("openai")
        out = provider._build_messages(
            [{"role": "user", "content": "hi"}], system_instruction="Be brief"
        )
        assert out[0] == {"role": "system", "content": "Be brief"}
        assert out[1] == {"role": "user", "content": "hi"}


def test_openai_parse_tool_calls_normalizes_shape():
    from agentkit.runtime.providers.openai import OpenAIProvider

    raw = [
        SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(name="lookup", arguments='{"q": "x"}'),
        )
    ]
    assert OpenAIProvider._parse_tool_calls(raw) == [
        {"id": "call_1", "name": "lookup", "arguments": {"q": "x"}}
    ]


def test_openai_parse_tool_calls_handles_bad_json():
    from agentkit.runtime.providers.openai import OpenAIProvider

    raw = [SimpleNamespace(id="c", function=SimpleNamespace(name="n", arguments="{bad"))]
    assert OpenAIProvider._parse_tool_calls(raw)[0]["arguments"] == {}


@pytest.mark.asyncio
async def test_openai_generate_translates_tools_and_parses_response():
    """generate() sends OpenAI-format tools and returns a normalized response."""
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="hello",
                        tool_calls=[
                            SimpleNamespace(
                                id="c1",
                                function=SimpleNamespace(name="lookup", arguments="{}"),
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=3, completion_tokens=2, total_tokens=5
            ),
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    with patch("agentkit.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = get_provider("openai")
        provider._client = fake_client  # bypass real AsyncOpenAI construction

        neutral_tools = [
            {"name": "lookup", "description": "Look up.", "parameters": {"type": "object"}}
        ]
        result = await provider.generate(
            messages=[{"role": "user", "content": "hi"}],
            tools=neutral_tools,
        )

    # Tools were translated to OpenAI's function-tool shape at the boundary.
    assert captured["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up.",
                "parameters": {"type": "object"},
            },
        }
    ]
    # Response normalized into the neutral GenerateResponse.
    assert result.text == "hello"
    assert result.tool_calls == [{"id": "c1", "name": "lookup", "arguments": {}}]
    assert result.metrics.total_tokens == 5
    assert result.metadata.provider_name == "openai"
