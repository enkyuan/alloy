"""Unit tests for the Anthropic provider.

All tests are fully mocked — no ANTHROPIC_API_KEY is required.

Patching convention: patch ``agentkit.runtime.providers.anthropic.get_settings``
(the module-local binding), NOT ``agentkit.core.config.get_settings``.  The
latter has no effect after the module is imported because the provider binds
``get_settings`` at import time.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentkit.runtime.providers.errors import ProviderConfigError

# Patch target: the binding used inside the provider module.
_PATCH = "agentkit.runtime.providers.anthropic.get_settings"

_FAKE_SETTINGS = dict(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-sonnet-4-6")


def _provider():
    """Return a freshly constructed AnthropicProvider with a mocked key."""
    from agentkit.runtime.providers.anthropic import AnthropicProvider

    with patch(_PATCH) as mock_gs:
        mock_gs.return_value = MagicMock(**_FAKE_SETTINGS)
        return AnthropicProvider()


# ---------------------------------------------------------------------------
# Loading / registration
# ---------------------------------------------------------------------------


def test_anthropic_provider_registered_and_loadable():
    from agentkit.runtime.providers.anthropic import AnthropicProvider

    assert AnthropicProvider is not None


def test_anthropic_provider_requires_api_key():
    from agentkit.runtime.providers.anthropic import AnthropicProvider

    with patch(_PATCH) as mock_gs:
        mock_gs.return_value = MagicMock(ANTHROPIC_API_KEY=None, ANTHROPIC_MODEL="claude-sonnet-4-6")
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider()


# ---------------------------------------------------------------------------
# _split_messages (delegates to format_messages_anthropic)
# ---------------------------------------------------------------------------


def test_anthropic_split_messages_extracts_system():
    provider = _provider()
    system, messages = provider._split_messages(
        [{"role": "user", "content": "hi"}], system_instruction="Be helpful"
    )
    assert system == "Be helpful"
    assert messages == [{"role": "user", "content": "hi"}]


def test_anthropic_split_messages_no_system():
    provider = _provider()
    system, messages = provider._split_messages([{"role": "user", "content": "hi"}], None)
    assert system is None
    assert len(messages) == 1


def test_anthropic_split_messages_role_system_absorbed():
    provider = _provider()
    system, messages = provider._split_messages(
        [{"role": "system", "content": "You are helpful"}, {"role": "user", "content": "hi"}],
        system_instruction=None,
    )
    assert system == "You are helpful"
    assert all(m["role"] != "system" for m in messages)


def test_anthropic_split_messages_tool_result_becomes_user_block():
    """Tool results must become Anthropic tool_result content blocks, not assistant text."""
    provider = _provider()
    _, messages = provider._split_messages(
        [
            {"role": "user", "content": "do something"},
            {"role": "tool", "name": "lookup", "content": "42", "tool_call_id": "c-1"},
        ],
        system_instruction=None,
    )
    tool_msg = next(m for m in messages if isinstance(m.get("content"), list))
    assert tool_msg["role"] == "user"
    block = tool_msg["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "c-1"
    assert block["content"] == "42"


# ---------------------------------------------------------------------------
# _parse_tool_use
# ---------------------------------------------------------------------------


def test_anthropic_parse_tool_use_extracts_text_and_tools():
    provider = _provider()
    text_block = SimpleNamespace(type="text", text="Hello")
    tool_block = SimpleNamespace(type="tool_use", id="c1", name="lookup", input={"q": "x"})
    text, tool_calls = provider._parse_tool_use([text_block, tool_block])
    assert text == "Hello"
    assert tool_calls == [{"id": "c1", "name": "lookup", "arguments": {"q": "x"}}]


def test_anthropic_parse_tool_use_handles_dict_blocks():
    provider = _provider()
    text, tool_calls = provider._parse_tool_use(
        [{"type": "tool_use", "id": "c2", "name": "search", "input": {"q": "y"}}]
    )
    assert text == ""
    assert tool_calls[0] == {"id": "c2", "name": "search", "arguments": {"q": "y"}}


def test_anthropic_parse_tool_use_empty():
    provider = _provider()
    text, tool_calls = provider._parse_tool_use([])
    assert text == ""
    assert tool_calls == []


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_generate_returns_normalized_response():
    provider = _provider()
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Hello!")],
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_response)
    provider._client = fake_client

    result = await provider.generate([{"role": "user", "content": "hi"}])

    assert result.text == "Hello!"
    assert result.tool_calls == []
    assert result.metrics is not None
    assert result.metrics.prompt_tokens == 5
    assert result.metrics.completion_tokens == 3


@pytest.mark.asyncio
async def test_anthropic_generate_with_tools_passes_translated_payload():
    provider = _provider()
    captured: dict = {}

    async def fake_create(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", id="c1", name="search", input={"q": "test"})
            ],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        )

    fake_client = MagicMock()
    fake_client.messages.create = fake_create
    provider._client = fake_client

    neutral_tools = [{"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {}}}]
    result = await provider.generate([{"role": "user", "content": "find x"}], tools=neutral_tools)

    assert "tools" in captured
    assert result.tool_calls[0]["name"] == "search"
    assert result.tool_calls[0]["arguments"] == {"q": "test"}


# ---------------------------------------------------------------------------
# generate_stream()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_generate_stream_yields_text_chunks():
    provider = _provider()
    text_delta = SimpleNamespace(type="text_delta", text="Hello")

    async def fake_stream_iter():
        yield SimpleNamespace(type="content_block_delta", delta=text_delta)

    fake_stream = MagicMock()
    fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
    fake_stream.__aexit__ = AsyncMock(return_value=False)
    fake_stream.__aiter__ = lambda self: fake_stream_iter()

    fake_client = MagicMock()
    fake_client.messages.stream = MagicMock(return_value=fake_stream)
    provider._client = fake_client

    chunks = []
    async for chunk in provider.generate_stream([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    assert any(c.delta == "Hello" for c in chunks)


@pytest.mark.asyncio
async def test_anthropic_generate_stream_reassembles_tool_use():
    """Streaming tool_use blocks must be accumulated and yielded as one call."""
    provider = _provider()
    tool_block_start = SimpleNamespace(type="tool_use", id="c1", name="lookup")
    json_delta_1 = SimpleNamespace(type="input_json_delta", partial_json='{"q":')
    json_delta_2 = SimpleNamespace(type="input_json_delta", partial_json='"test"}')

    events = [
        SimpleNamespace(type="content_block_start", content_block=tool_block_start),
        SimpleNamespace(type="content_block_delta", delta=json_delta_1),
        SimpleNamespace(type="content_block_delta", delta=json_delta_2),
        SimpleNamespace(type="content_block_stop"),
    ]

    async def fake_stream_iter():
        for e in events:
            yield e

    fake_stream = MagicMock()
    fake_stream.__aenter__ = AsyncMock(return_value=fake_stream)
    fake_stream.__aexit__ = AsyncMock(return_value=False)
    fake_stream.__aiter__ = lambda self: fake_stream_iter()

    fake_client = MagicMock()
    fake_client.messages.stream = MagicMock(return_value=fake_stream)
    provider._client = fake_client

    chunks = []
    async for chunk in provider.generate_stream([{"role": "user", "content": "hi"}]):
        chunks.append(chunk)

    tool_chunks = [c for c in chunks if c.tool_calls]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].tool_calls[0]["name"] == "lookup"
    assert tool_chunks[0].tool_calls[0]["arguments"] == {"q": "test"}
