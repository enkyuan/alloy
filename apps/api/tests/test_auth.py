import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock, patch, AsyncMock

# We need to mock `supabase_auth_service` since it makes external calls.
# We will patch it where it is imported in `app.routers.auth`

@pytest.fixture
def mock_supabase_auth():
    with patch("app.routers.auth.supabase_auth_service") as mock:
        mock.get_user = AsyncMock()
        mock.refresh_token = AsyncMock()
        yield mock

@pytest.mark.asyncio
async def test_sync_user_missing_header(async_client: AsyncClient):
    response = await async_client.post("/api/v1/auth/sync")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid authorization header"

@pytest.mark.asyncio
async def test_sync_user_success(async_client: AsyncClient, mock_supabase_auth):
    # Mock Supabase user response
    mock_supabase_auth.get_user.return_value = {
        "id": "test_user_id",
        "email": "test@example.com",
        "user_metadata": {
            "full_name": "Test User",
            "avatar_url": "http://example.com/avatar.jpg"
        },
        "app_metadata": {"provider": "google"}
    }

    headers = {"Authorization": "Bearer valid_token"}
    response = await async_client.post("/api/v1/auth/sync", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test_user_id"
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"
    
    # Verify user is actually in DB by calling /me
    # We must mock get_user again for /me call if we called it separately, 
    # but here we just check the response of sync.

@pytest.mark.asyncio
async def test_get_me_success(async_client: AsyncClient, mock_supabase_auth, session):
    # First, insert a user into the DB (or use the sync endpoint to create one)
    # Let's insert manually to be independent
    from app.models.user import User
    from datetime import datetime, timezone
    
    db_user = User(
        id="existing_user_id",
        email="existing@example.com",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(db_user)
    session.commit()
    
    # Mock Supabase validation
    mock_supabase_auth.get_user.return_value = {
        "id": "existing_user_id",
        "email": "existing@example.com"
    }

    headers = {"Authorization": "Bearer any_token"}
    response = await async_client.get("/api/v1/auth/me", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "existing_user_id"
    assert data["email"] == "existing@example.com"

