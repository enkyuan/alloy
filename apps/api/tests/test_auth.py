
import pytest
from httpx import AsyncClient
from app.models.user import User

@pytest.mark.asyncio
async def test_auth_sync_new_user(async_client: AsyncClient, mock_supabase_auth, session):
    # Mock Supabase user with enough data
    mock_supabase_auth.get_user.return_value = {
        "id": "new_user_id",
        "email": "newuser@example.com",
        "user_metadata": {
            "full_name": "New User",
            "avatar_url": "http://avatar.url",
        }
    }

    headers = {"Authorization": "Bearer valid_token"}
    response = await async_client.post("/api/v1/auth/sync", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "new_user_id"
    assert data["email"] == "newuser@example.com"
    
    # Verify DB
    user = session.query(User).filter(User.id == "new_user_id").first()
    assert user is not None
    assert user.email == "newuser@example.com"

@pytest.mark.asyncio
async def test_auth_me_success(async_client: AsyncClient, mock_supabase_auth, session):
    # Setup - must create user in DB first because /me checks DB
    user = User(
        id="existing_user_id", 
        email="existing@example.com",
        username="existing",
        is_verified=True
    )
    session.add(user)
    session.flush()

    mock_supabase_auth.get_user.return_value = {
        "id": "existing_user_id",
        "email": "existing@example.com"
    }

    headers = {"Authorization": "Bearer valid_token"}
    response = await async_client.get("/api/v1/auth/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "existing_user_id"
    assert data["email"] == "existing@example.com"

@pytest.mark.asyncio
async def test_auth_refresh_token(async_client: AsyncClient, mock_supabase_auth, session):
    # Setup user in DB
    user = User(id="refresh_user_id", email="refresh@example.com")
    session.add(user)
    session.flush()

    # Mock Refresh Response
    mock_supabase_auth.refresh_token.return_value = {
        "user": {"id": "refresh_user_id"},
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600
    }

    payload = {"refresh_token": "old_refresh_token"}
    response = await async_client.post("/api/v1/auth/refresh", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"] == "new_access_token"
    mock_supabase_auth.refresh_token.assert_called_once_with("old_refresh_token")
