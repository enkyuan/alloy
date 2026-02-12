import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.fixture
def mock_supabase():
    with patch("app.routers.routers_gemini.supabase_auth_service") as mock:
        mock.get_user = AsyncMock(return_value={"id": "test_user_id"})
        yield mock

@pytest.fixture
def mock_gemini_service():
    with patch("app.routers.routers_gemini.get_gemini_service") as mock_get:
        service_mock = MagicMock()
        service_mock.generate_response = AsyncMock(return_value="Mocked response")
        service_mock.generate_chat_response = AsyncMock()
        
        # chat response object usually has a text attribute
        chat_resp = MagicMock()
        chat_resp.text = "Mocked chat response"
        service_mock.generate_chat_response.return_value = chat_resp
        
        # streaming response is an async generator
        async def mock_stream(*args, **kwargs):
            yield "Chunk 1"
            yield "Chunk 2"
        
        service_mock.generate_streaming_response = mock_stream
        
        mock_get.return_value = service_mock
        yield service_mock

@pytest.mark.asyncio
async def test_generate_text(async_client: AsyncClient, mock_supabase, mock_gemini_service):
    headers = {"Authorization": "Bearer token"}
    payload = {"prompt": "Hello"}
    response = await async_client.post("/api/v1/gemini/generate", headers=headers, json=payload)
    
    assert response.status_code == 200
    assert response.json()["text"] == "Mocked response"
    mock_gemini_service.generate_response.assert_called_once()

@pytest.mark.asyncio
async def test_chat_completion(async_client: AsyncClient, mock_supabase, mock_gemini_service):
    headers = {"Authorization": "Bearer token"}
    payload = {
        "messages": [{"role": "user", "content": "Hi"}],
        "temperature": 0.5
    }
    response = await async_client.post("/api/v1/gemini/chat", headers=headers, json=payload)
    
    assert response.status_code == 200
    assert response.json()["text"] == "Mocked chat response"
    mock_gemini_service.generate_chat_response.assert_called_once()

@pytest.mark.asyncio
async def test_generate_stream(async_client: AsyncClient, mock_supabase, mock_gemini_service):
    headers = {"Authorization": "Bearer token"}
    payload = {"prompt": "Stream me"}
    
    # Use standard request for stream endpoint in test client (httpx handles streaming response)
    async with async_client.stream("POST", "/api/v1/gemini/stream", headers=headers, json=payload) as response:
        assert response.status_code == 200
        content = [chunk async for chunk in response.aiter_text()]
        combined = "".join(content)
        assert "Chunk 1" in combined
        assert "Chunk 2" in combined
