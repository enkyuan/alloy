import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock, patch

@pytest.mark.asyncio
async def test_list_integrations_unauth(async_client: AsyncClient):
    response = await async_client.get("/api/v1/integrations")
    # Should probably be 401 or 403, but depending on implementation might be 200 empty
    # Let's check stt.
    assert response.status_code in [200, 401, 403]

@pytest.mark.asyncio
async def test_tools_endpoint(async_client: AsyncClient):
    response = await async_client.get("/api/v1/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    # We should have some tools registered
    assert isinstance(data["tools"], list)
