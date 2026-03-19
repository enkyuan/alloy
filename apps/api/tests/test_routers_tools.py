import pytest
from httpx import AsyncClient
from unittest.mock import patch, MagicMock
import fakeredis.aioredis


@pytest.fixture
def mock_tool_specs():
    with patch("app.routers.routers_tools.list_tool_specs") as mock:
        # Mock ToolSpec object
        spec = MagicMock()
        spec.name = "test_tool"
        spec.description = "A test tool"
        spec.parameters = {"type": "object"}

        mock.return_value = [spec]
        yield mock


@pytest.fixture
def mock_redis():
    fake_redis = fakeredis.aioredis.FakeRedis()

    async def get_redis():
        return fake_redis

    # Patch the function in app.routers.routers_tools since it calls it directly
    with patch("app.routers.routers_tools.get_redis_client", side_effect=get_redis):
        yield fake_redis


@pytest.mark.asyncio
async def test_routers_tools_list_tools(async_client: AsyncClient, mock_tool_specs):
    response = await async_client.get("/api/v1/tools")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "test_tool"
    assert data["tools"][0]["description"] == "A test tool"


@pytest.mark.asyncio
async def test_routers_tools_cache_metrics(
    async_client: AsyncClient, mock_redis, mock_supabase_auth
):
    # Pre-populate fake redis
    await mock_redis.set("agent:cache:hit", 10)
    await mock_redis.set("agent:cache:miss", 5)
    mock_supabase_auth.get_user.return_value = {"id": "test_user_tools"}

    response = await async_client.get(
        "/api/v1/tools/cache/metrics",
        headers={"Authorization": "Bearer valid_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hit"] == 10
    assert data["miss"] == 5


@pytest.mark.asyncio
async def test_routers_tools_clear_cache(
    async_client: AsyncClient, mock_redis, mock_supabase_auth
):
    # Pre-populate fake redis
    await mock_redis.set("agent:cache:hit", 10)
    await mock_redis.set("agent:cache:temp", "val")
    mock_supabase_auth.get_user.return_value = {"id": "test_user_tools"}

    response = await async_client.post(
        "/api/v1/tools/cache/clear",
        headers={"Authorization": "Bearer valid_token"},
    )
    assert response.status_code == 200
    # It should delete keys starting with prefix AND the hit/miss keys

    # Verify keys are gone
    assert await mock_redis.get("agent:cache:hit") is None
