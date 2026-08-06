from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from kaji.runtime.providers.errors import (
    ProviderConnectionError,
    ProviderRateLimitedError,
)
from kaji.runtime.providers.types import (
    GenerateResponse as ProviderGenerateResponse,
    ModelResponseChunk,
)
from kaji_serve.server.app import app
from kaji_serve.server.v1.providers import provide_gemini_provider


@pytest.fixture
def mock_gemini_provider():
    provider_mock = MagicMock()

    async def mock_generate(*, messages, **_kwargs):
        text = "Mocked chat response" if len(messages) > 1 else "Mocked response"
        return ProviderGenerateResponse(text=text)

    provider_mock.generate = AsyncMock(side_effect=mock_generate)

    async def mock_stream(*args, **kwargs):
        yield ModelResponseChunk(delta="Chunk 1")
        yield ModelResponseChunk(delta="Chunk 2")

    provider_mock.generate_stream = MagicMock(side_effect=mock_stream)

    app.dependency_overrides[provide_gemini_provider] = lambda: provider_mock
    yield provider_mock
    app.dependency_overrides.pop(provide_gemini_provider, None)


@pytest.mark.asyncio
async def test_api_providers_generate_text(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    payload = {"prompt": "Hello"}
    response = await async_client.post(
        "/api/v1/gemini/generate", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Mocked response"
    mock_gemini_provider.generate.assert_awaited_once_with(
        messages=[{"role": "user", "content": "Hello"}],
        system_instruction=None,
        temperature=0.7,
        max_tokens=None,
    )


@pytest.mark.asyncio
async def test_api_providers_generate_rejects_empty_prompt(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    response = await async_client.post(
        "/api/v1/gemini/generate", headers=headers, json={"prompt": ""}
    )

    assert response.status_code == 422
    mock_gemini_provider.generate.assert_not_called()


@pytest.mark.asyncio
async def test_api_providers_generate_maps_rate_limit_error(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    mock_gemini_provider.generate.side_effect = ProviderRateLimitedError(
        service="gemini",
        action="generate",
        message="rate limited",
    )
    headers = {"Authorization": "Bearer token"}
    response = await async_client.post(
        "/api/v1/gemini/generate", headers=headers, json={"prompt": "Hello"}
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "gemini rate limit reached"


@pytest.mark.asyncio
async def test_api_providers_generate_maps_network_error(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    mock_gemini_provider.generate.side_effect = ProviderConnectionError(
        service="gemini",
        action="generate",
        message="network failed",
    )
    headers = {"Authorization": "Bearer token"}
    response = await async_client.post(
        "/api/v1/gemini/generate", headers=headers, json={"prompt": "Hello"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "gemini is temporarily unavailable"


@pytest.mark.asyncio
async def test_api_providers_chat_completion(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    payload = {
        "messages": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "hello"},
        ],
        "temperature": 0.5,
    }
    response = await async_client.post(
        "/api/v1/gemini/chat", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Mocked chat response"
    mock_gemini_provider.generate.assert_awaited_once_with(
        messages=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "hello"},
        ],
        system_instruction=None,
        temperature=0.5,
    )


@pytest.mark.asyncio
async def test_api_providers_chat_accepts_gemini_model_role(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    payload = {
        "messages": [
            {"role": "user", "content": "Hi"},
            {"role": "model", "content": "hello"},
        ],
    }
    response = await async_client.post(
        "/api/v1/gemini/chat", headers=headers, json=payload
    )

    assert response.status_code == 200
    called_messages = mock_gemini_provider.generate.call_args.kwargs["messages"]
    assert called_messages[1]["role"] == "model"


@pytest.mark.asyncio
async def test_api_providers_chat_rejects_invalid_role(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    payload = {"messages": [{"role": "hacker", "content": "Hi"}]}
    response = await async_client.post(
        "/api/v1/gemini/chat", headers=headers, json=payload
    )

    assert response.status_code == 422
    mock_gemini_provider.generate.assert_not_called()


@pytest.mark.asyncio
async def test_api_providers_generate_stream(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    headers = {"Authorization": "Bearer token"}
    payload = {"prompt": "Stream me"}

    # Use standard request for stream endpoint in test client (httpx handles streaming response)
    async with async_client.stream(
        "POST", "/api/v1/gemini/stream", headers=headers, json=payload
    ) as response:
        assert response.status_code == 200
        content = [chunk async for chunk in response.aiter_text()]
        combined = "".join(content)
        assert "Chunk 1" in combined
        assert "Chunk 2" in combined
    mock_gemini_provider.generate_stream.assert_called_once_with(
        messages=[{"role": "user", "content": "Stream me"}],
        system_instruction=None,
        temperature=0.7,
        max_tokens=None,
    )


@pytest.mark.asyncio
async def test_api_providers_stream_maps_error_before_headers(
    async_client: AsyncClient, mock_current_user, mock_gemini_provider
):
    async def error_stream(*args, **kwargs):
        raise ProviderRateLimitedError(
            service="gemini",
            action="stream",
            message="rate limited",
        )
        yield ""

    mock_gemini_provider.generate_stream = error_stream

    response = await async_client.post(
        "/api/v1/gemini/stream",
        headers={"Authorization": "Bearer token"},
        json={"prompt": "Stream me"},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "gemini rate limit reached"
