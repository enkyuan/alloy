import pytest

from agentkit.runtime.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_mock_provider_generate_returns_canned_text():
    provider = MockProvider()
    response = await provider.generate(messages=[{"role": "user", "content": "hi"}])
    assert response.text == "mock response"
    assert response.tool_calls == []


@pytest.mark.asyncio
async def test_mock_provider_stream_yields_delta():
    provider = MockProvider()
    chunks = [chunk async for chunk in provider.generate_stream(messages=[])]
    assert len(chunks) == 1
    assert chunks[0].delta == "mock"
