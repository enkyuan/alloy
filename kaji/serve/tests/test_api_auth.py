import pytest
from httpx import AsyncClient
from sqlalchemy import select

from kaji_serve.server.deps import get_current_supabase_user
from kaji_serve.server.app import app
from kaji_serve.server.models.user import User


@pytest.fixture
def mock_sync_user():
    async def override_current_user() -> dict:
        return {
            "id": "new_user_id",
            "sub": "new_user_id",
            "email": "newuser@example.com",
            "user_metadata": {
                "full_name": "New User",
                "avatar_url": "http://avatar.url",
            },
        }

    app.dependency_overrides[get_current_supabase_user] = override_current_user
    yield override_current_user
    app.dependency_overrides.pop(get_current_supabase_user, None)


@pytest.fixture
def mock_existing_user():
    async def override_current_user() -> dict:
        return {
            "id": "existing_user_id",
            "sub": "existing_user_id",
            "email": "existing@example.com",
        }

    app.dependency_overrides[get_current_supabase_user] = override_current_user
    yield override_current_user
    app.dependency_overrides.pop(get_current_supabase_user, None)


@pytest.mark.asyncio
@pytest.mark.db
async def test_api_auth_sync_new_user(
    db_async_client: AsyncClient, mock_sync_user, session
):
    headers = {"Authorization": "Bearer valid_token"}
    response = await db_async_client.post("/api/v1/auth/sync", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "new_user_id"
    assert data["email"] == "newuser@example.com"

    result = await session.execute(select(User).where(User.id == "new_user_id"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "newuser@example.com"


@pytest.mark.asyncio
@pytest.mark.db
async def test_api_auth_me_success(
    db_async_client: AsyncClient, mock_existing_user, session
):
    user = User(
        id="existing_user_id",
        email="existing@example.com",
        username="existing",
        is_verified=True,
    )
    session.add(user)
    await session.flush()

    headers = {"Authorization": "Bearer valid_token"}
    response = await db_async_client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "existing_user_id"
    assert data["email"] == "existing@example.com"


@pytest.mark.asyncio
@pytest.mark.db
async def test_api_auth_refresh_token(
    db_async_client: AsyncClient, mock_supabase_auth, session
):
    user = User(id="refresh_user_id", email="refresh@example.com")
    session.add(user)
    await session.flush()

    mock_supabase_auth.refresh_token.return_value = {
        "user": {"id": "refresh_user_id"},
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600,
    }

    payload = {"refresh_token": "old_refresh_token"}
    response = await db_async_client.post("/api/v1/auth/refresh", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"] == "new_access_token"
    mock_supabase_auth.refresh_token.assert_called_once_with("old_refresh_token")


@pytest.mark.asyncio
async def test_api_auth_sync_requires_valid_token(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/auth/sync",
        headers={"Authorization": "Bearer invalid_token"},
    )

    assert response.status_code == 401
