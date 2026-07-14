from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kaji.runtime.agents.cancellation import CancellationToken
from kaji.runtime.agents.context import TurnContext
from kaji.runtime.agents.planner import ToolPlanner
from kaji.runtime.providers.errors import (
    ProviderConfigError,
    ProviderConnectionError,
    ProviderRateLimitedError,
)
from kaji.runtime.providers.openai import OpenAIProvider
from kaji.runtime.providers.registry import get_provider
from kaji.runtime.tools.registry import ToolSpec


class FakeProviderHTTPError(RuntimeError):
    def __init__(self, message: str, *, status: int, response_text: str) -> None:
        super().__init__(message)
        self.status = status
        self.response = SimpleNamespace(text=response_text)


def test_openai_provider_registered_and_loadable():
    assert OpenAIProvider is not None


def test_openai_provider_constructor_does_not_create_vendor_client():
    with (
        patch("kaji.runtime.providers.openai.get_settings") as settings,
        patch("kaji.runtime.providers.openai.import_module") as import_module,
    ):
        settings.return_value = SimpleNamespace()
        provider = OpenAIProvider(
            api_key="fixture", model="gpt-5.4-mini", base_url="https://fixture.invalid"
        )

    assert provider._client is None
    import_module.assert_not_called()


def test_openai_provider_requires_api_key():
    with patch("kaji.core.config.settings.OPENAI_API_KEY", None):
        with pytest.raises(ProviderConfigError, match="OPENAI_API_KEY"):
            get_provider("openai")


def test_openai_provider_builds_messages_with_system():
    with patch("kaji.core.config.settings.OPENAI_API_KEY", "test-key"):
        provider = OpenAIProvider()
        out = provider._build_messages(
            [{"role": "user", "content": "hi"}], system_instruction="Be brief"
        )
        assert out[0] == {"role": "system", "content": "Be brief"}
        assert out[1] == {"role": "user", "content": "hi"}


def test_openai_parse_tool_calls_normalizes_shape():
    from kaji.runtime.providers.openai import OpenAIProvider

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
    from kaji.runtime.providers.openai import OpenAIProvider

    raw = [
        SimpleNamespace(id="c", function=SimpleNamespace(name="n", arguments="{bad"))
    ]
    assert "__parse_error" in OpenAIProvider._parse_tool_calls(raw)[0]["arguments"]


@pytest.mark.asyncio
async def test_openai_bad_json_tool_args_fail_closed_in_planner():
    emitted = []
    executed = False

    async def executor(_invocation):
        nonlocal executed
        executed = True
        return {"ok": True}

    planner = ToolPlanner(
        executor=executor,
        specs={
            "n": ToolSpec(
                name="n",
                description="No-op.",
                parameters={"type": "object", "properties": {}, "required": []},
                risk="read",
            )
        },
    )
    call = OpenAIProvider._parse_tool_calls(
        [SimpleNamespace(id="c", function=SimpleNamespace(name="n", arguments="{bad"))]
    )[0]

    async def emit(event):
        emitted.append(event)

    await planner.execute_batch(
        "s1",
        [call],
        emit,
        turn_id="test-turn",
        turn_context=TurnContext(principal_id="test-principal"),
        cancellation_token=CancellationToken(),
    )

    assert executed is False
    assert emitted[-1].type.value == "tool.call.failed"


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

    with patch("kaji.core.config.settings.OPENAI_API_KEY", "test-key"):
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
    assert result.cost_usd == 0.00001125


@pytest.mark.asyncio
async def test_openai_generate_omits_cost_without_usage() -> None:
    async def fake_create(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]))
            ]
        )

    provider = OpenAIProvider(api_key="test-key")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    result = await provider.generate(messages=[{"role": "user", "content": "hi"}])

    assert result.cost_usd is None


@pytest.mark.asyncio
async def test_openai_generate_omits_cost_for_unpriced_model() -> None:
    async def fake_create(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]))
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    provider = OpenAIProvider(api_key="test-key", model="routed/unknown-model")
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    result = await provider.generate(messages=[{"role": "user", "content": "hi"}])

    assert result.metrics is not None
    assert result.metrics.total_tokens == 5
    assert result.cost_usd is None


@pytest.mark.asyncio
async def test_openai_generate_maps_rate_limits_to_provider_error():
    async def fake_create(**_kwargs):
        raise FakeProviderHTTPError("slow down", status=429, response_text="slow down")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    provider = OpenAIProvider(api_key="test-key")
    provider._client = fake_client

    with pytest.raises(ProviderRateLimitedError):
        await provider.generate(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_openai_generate_maps_transport_errors_to_network_error():
    async def fake_create(**_kwargs):
        raise OSError("network down")

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    provider = OpenAIProvider(api_key="test-key")
    provider._client = fake_client

    with pytest.raises(ProviderConnectionError):
        await provider.generate(messages=[{"role": "user", "content": "hi"}])


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

    with patch("kaji.core.config.settings.OPENAI_API_KEY", "test-key"):
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


@pytest.mark.parametrize(
    ("model", "has_known_cost"),
    [("gpt-5.4-mini", True), ("routed/unknown-model", False)],
)
@pytest.mark.asyncio
async def test_openai_stream_yields_usage_metadata_chunk(
    model: str, has_known_cost: bool
):
    captured: dict = {}

    class FakeStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="hi", tool_calls=None)
                    )
                ],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=3,
                    completion_tokens=2,
                    total_tokens=5,
                ),
            )

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeStream()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    provider = OpenAIProvider(api_key="test-key", model=model)
    provider._client = fake_client

    chunks = [chunk async for chunk in provider.generate_stream(messages=[], tools=[])]

    assert captured["stream_options"] == {"include_usage": True}
    assert chunks[0].delta == "hi"
    assert chunks[-1].metrics is not None
    assert chunks[-1].metrics.prompt_tokens == 3
    assert chunks[-1].metrics.completion_tokens == 2
    if has_known_cost:
        assert chunks[-1].cost_usd is not None
        assert chunks[-1].cost_usd > 0
    else:
        assert chunks[-1].cost_usd is None


def test_format_messages_openai_preserves_tool_call_id():
    """Tool messages must carry tool_call_id so multi-turn loops work."""
    from kaji.runtime.providers._translate import format_messages_openai

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
    from kaji.runtime.providers._translate import format_messages_openai

    messages = [{"role": "tool", "name": "lookup", "content": "ok"}]
    formatted = format_messages_openai(messages)
    assert formatted[0]["tool_call_id"] == "lookup"
