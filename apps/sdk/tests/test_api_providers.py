from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.fixture
def mock_gemini_service():
    with patch("sdk.api.v1.providers.get_gemini_service") as mock_get:
        service_mock = MagicMock()

        chat_resp = MagicMock()
        chat_resp.text = "Mocked chat response"

        service_mock.generate_response = AsyncMock(return_value="Mocked response")
        service_mock.generate_chat_response = AsyncMock(return_value=chat_resp)

        async def mock_stream(*args, **kwargs):
            yield "Chunk 1"
            yield "Chunk 2"

        service_mock.generate_streaming_response = mock_stream

        mock_get.return_value = service_mock
        yield service_mock


@pytest.mark.asyncio
async def test_api_providers_generate_text(
    async_client: AsyncClient, mock_current_user, mock_gemini_service
):
    headers = {"Authorization": "Bearer token"}
    payload = {"prompt": "Hello"}
    response = await async_client.post(
        "/api/v1/gemini/generate", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Mocked response"
    mock_gemini_service.generate_response.assert_called_once()


@pytest.mark.asyncio
async def test_api_providers_chat_completion(
    async_client: AsyncClient, mock_current_user, mock_gemini_service
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
    mock_gemini_service.generate_chat_response.assert_called_once()


@pytest.mark.asyncio
async def test_api_providers_generate_stream(
    async_client: AsyncClient, mock_current_user, mock_gemini_service
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
