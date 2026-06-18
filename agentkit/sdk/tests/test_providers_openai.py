from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agentkit.runtime.providers.errors import ProviderConfigError
from agentkit.runtime.providers.openai import OpenAIProvider
from agentkit.runtime.providers.registry import get_provider


def test_openai_provider_registered_and_loadable():
    assert OpenAIProvider is not None


def test_openai_provider_requires_api_key():
    with patch("agentkit.core.config.settings.OPENAI_API_KEY", None):
        with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
            get_provider("openai")


def test_openai_provider_builds_messages_with_system():
    with patch("agentkit.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = OpenAIProvider()
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

    raw = [
        SimpleNamespace(id="c", function=SimpleNamespace(name="n", arguments="{bad"))
    ]
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
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    with patch("agentkit.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = OpenAIProvider()
        provider._client = fake_client  # bypass real AsyncOpenAI construction

        neutral_tools = [
            {
                "name": "lookup",
                "description": "Look up.",
                "parameters": {"type": "object"},
            }
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
    assert result.metrics is not None
    assert result.metadata is not None
    assert result.metrics.total_tokens == 5
    assert result.metadata.provider_name == "openai"


@pytest.mark.asyncio
async def test_openai_stream_accumulates_fragmented_tool_call_arguments():
    class FakeStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="lookup", arguments='{"q":'
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id=None,
                                    function=SimpleNamespace(
                                        name=None, arguments='"weather"}'
                                    ),
                                )
                            ],
                        )
                    )
                ]
            )

    async def fake_create(**_kwargs):
        return FakeStream()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    with patch("agentkit.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = OpenAIProvider()
        provider._client = fake_client
        chunks = [
            chunk async for chunk in provider.generate_stream(messages=[], tools=[])
        ]

    assert len(chunks) == 1
    assert chunks[0].delta == ""
    assert chunks[0].tool_calls == [
        {"id": "call-1", "name": "lookup", "arguments": {"q": "weather"}}
    ]


def test_format_messages_openai_preserves_tool_call_id():
    """Tool messages must carry tool_call_id so multi-turn loops work."""
    from agentkit.runtime.providers._translate import format_messages_openai

    messages = [
        {"role": "user", "content": "hello"},
        {
            "role": "tool",
            "name": "lookup",
            "content": '{"x": 1}',
            "tool_call_id": "c-1",
        },
    ]
    formatted = format_messages_openai(messages)
    tool_msg = next(m for m in formatted if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c-1"
    assert tool_msg["content"] == '{"x": 1}'


def test_format_messages_openai_falls_back_to_name_when_no_id():
    from agentkit.runtime.providers._translate import format_messages_openai

    messages = [{"role": "tool", "name": "lookup", "content": "ok"}]
    formatted = format_messages_openai(messages)
    assert formatted[0]["tool_call_id"] == "lookup"
