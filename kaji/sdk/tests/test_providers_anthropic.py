"""Unit tests for the Anthropic provider.

All tests are fully mocked — no ANTHROPIC_API_KEY is required.

Patching convention: patch ``kaji.runtime.providers.anthropic.get_settings``
(the module-local binding), NOT ``kaji.core.config.get_settings``.  The
latter has no effect after the module is imported because the provider binds
``get_settings`` at import time.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kaji.runtime.providers.errors import (
    ProviderConfigError,
    ServiceNetworkError,
    ServiceRateLimitError,
)

# Patch target: the binding used inside the provider module.
_PATCH = "kaji.runtime.providers.anthropic.get_settings"

_FAKE_SETTINGS = dict(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-sonnet-4-6")


class FakeProviderHTTPError(RuntimeError):
    def __init__(self, message: str, *, status: int, response_text: str) -> None:
        super().__init__(message)
        self.status = status
        self.response = SimpleNamespace(text=response_text)


def _provider(model: str = "claude-sonnet-4-6"):
    """Return a freshly constructed AnthropicProvider with a mocked key."""
    from kaji.runtime.providers.anthropic import AnthropicProvider

    with patch(_PATCH) as mock_gs:
        mock_gs.return_value = MagicMock(**_FAKE_SETTINGS)
        return AnthropicProvider(model=model)


# ---------------------------------------------------------------------------
# Loading / registration
# ---------------------------------------------------------------------------


def test_anthropic_provider_registered_and_loadable():
    from kaji.runtime.providers.anthropic import AnthropicProvider

    assert AnthropicProvider is not None


def test_anthropic_provider_constructor_does_not_create_vendor_client():
    from kaji.runtime.providers.anthropic import AnthropicProvider

    with (
        patch(_PATCH) as settings,
        patch("kaji.runtime.providers.anthropic.import_module") as import_module,
    ):
        settings.return_value = MagicMock()
        provider = AnthropicProvider(api_key="fixture", model="claude-sonnet-4-6")

    assert provider._client is None
    import_module.assert_not_called()


def test_anthropic_provider_requires_api_key():
    from kaji.runtime.providers.anthropic import AnthropicProvider

    with patch(_PATCH) as mock_gs:
        mock_gs.return_value = MagicMock(
            ANTHROPIC_API_KEY=None, ANTHROPIC_MODEL="claude-sonnet-4-6"
        )
        with pytest.raises(ProviderConfigError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider()


def test_anthropic_provider_honors_explicit_options():
    from kaji.runtime.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(api_key="explicit-key", model="explicit-model")

    assert provider.api_key == "explicit-key"
    assert provider.model_name == "explicit-model"


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
    system, messages = provider._split_messages(
        [{"role": "user", "content": "hi"}], None
    )
    assert system is None
    assert len(messages) == 1


def test_anthropic_split_messages_role_system_absorbed():
    provider = _provider()
    system, messages = provider._split_messages(
        [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ],
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
    tool_block = SimpleNamespace(
        type="tool_use", id="c1", name="lookup", input={"q": "x"}
    )
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
    assert result.cost_usd == 0.00006


@pytest.mark.asyncio
async def test_anthropic_generate_omits_cost_without_usage() -> None:
    provider = _provider()
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Hello!")]
        )
    )
    provider._client = fake_client

    result = await provider.generate([{"role": "user", "content": "hi"}])

    assert result.cost_usd is None


@pytest.mark.asyncio
async def test_anthropic_generate_omits_cost_for_unpriced_model() -> None:
    provider = _provider("routed/unknown-model")
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Hello!")],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )
    )
    provider._client = fake_client

    result = await provider.generate([{"role": "user", "content": "hi"}])

    assert result.metrics is not None
    assert result.metrics.total_tokens == 8
    assert result.cost_usd is None


@pytest.mark.asyncio
async def test_anthropic_generate_with_tools_passes_translated_payload():
    provider = _provider()
    captured: dict = {}

    async def fake_create(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="tool_use", id="c1", name="search", input={"q": "test"}
                )
            ],
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
        )

    fake_client = MagicMock()
    fake_client.messages.create = fake_create
    provider._client = fake_client

    neutral_tools = [
        {
            "name": "search",
            "description": "Search",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    result = await provider.generate(
        [{"role": "user", "content": "find x"}], tools=neutral_tools
    )

    assert "tools" in captured
    assert result.tool_calls[0]["name"] == "search"
    assert result.tool_calls[0]["arguments"] == {"q": "test"}


@pytest.mark.asyncio
async def test_anthropic_generate_maps_rate_limits_to_service_error():
    provider = _provider()

    async def fake_create(**_kwargs):
        raise FakeProviderHTTPError("slow down", status=429, response_text="rate limit")

    fake_client = MagicMock()
    fake_client.messages.create = fake_create
    provider._client = fake_client

    with pytest.raises(ServiceRateLimitError):
        await provider.generate([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_anthropic_generate_maps_transport_errors_to_network_error():
    provider = _provider()

    async def fake_create(**_kwargs):
        raise OSError("network down")

    fake_client = MagicMock()
    fake_client.messages.create = fake_create
    provider._client = fake_client

    with pytest.raises(ServiceNetworkError):
        await provider.generate([{"role": "user", "content": "hi"}])


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


@pytest.mark.parametrize(
    ("model", "has_known_cost"),
    [("claude-sonnet-4-6", True), ("routed/unknown-model", False)],
)
@pytest.mark.asyncio
async def test_anthropic_generate_stream_yields_usage_metadata_when_present(
    model: str, has_known_cost: bool
):
    provider = _provider(model)

    async def fake_stream_iter():
        yield SimpleNamespace(
            type="message_start",
            usage=SimpleNamespace(input_tokens=5, output_tokens=0),
        )
        yield SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="Hello"),
        )
        yield SimpleNamespace(
            type="message_delta",
            usage=SimpleNamespace(output_tokens=3),
        )

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
    metadata = chunks[-1]
    assert metadata.metrics is not None
    assert metadata.metrics.prompt_tokens == 5
    assert metadata.metrics.completion_tokens == 3
    if has_known_cost:
        assert metadata.cost_usd is not None
        assert metadata.cost_usd > 0
    else:
        assert metadata.cost_usd is None


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
