import pytest
from httpx import AsyncClient

from kaji_serve import __version__


@pytest.mark.asyncio
async def test_main_app_health_check(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["version"] == __version__


@pytest.mark.asyncio
async def test_main_app_root(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    assert response.json()["version"] == __version__
