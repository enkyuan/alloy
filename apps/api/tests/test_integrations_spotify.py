
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
import uuid

from app.models.integration import Integration
from app.models.user import User


@pytest.fixture
def mock_settings():
    with patch("app.routers.integrations.integrations_spotify.settings") as mock:
        mock.SPOTIFY_CLIENT_ID = "test_client_id"
        mock.SPOTIFY_CLIENT_SECRET = "test_client_secret"
        mock.SPOTIFY_REDIRECT_URI = "http://localhost/callback"
        yield mock

@pytest.fixture
def mock_redis_global():
    with patch("app.routers.integrations.integrations_spotify.redis_client") as mock:
        mock.setex = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock()
        yield mock

@pytest.mark.asyncio
async def test_get_spotify_oauth_url(async_client: AsyncClient, mock_supabase_auth, mock_settings, mock_redis_global):
    # Mock authenticating user
    mock_supabase_auth.get_user.return_value = {
        "id": "test_user_id",
        "email": "test@example.com"
    }

    headers = {"Authorization": "Bearer test_token"}
    response = await async_client.get("/api/v1/integrations/spotify/auth", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "authUrl" in data
    assert "state" in data
    assert "accounts.spotify.com/authorize" in data["authUrl"]
    assert "client_id=" in data["authUrl"]

@pytest.mark.asyncio
async def test_sync_spotify_integration(async_client: AsyncClient, mock_supabase_auth, session: Session):
    # 1. Setup Supabase user with Spotify identity
    user_id = str(uuid.uuid4())
    mock_supabase_auth.get_user.return_value = {
        "id": user_id,
        "email": "test@example.com",
        "identities": [
            {"provider": "spotify", "id": "spotify_user_123"}
        ]
    }
    
    # We need to insert the user into DB first because of FK constraint
    db_user = User(
        id=user_id,
        email="test@example.com",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(db_user)
    session.flush() # Use flush instead of commit to keep transaction alive

    # 2. Call sync endpoint
    headers = {"Authorization": "Bearer test_token"}
    payload = {
        "access_token": "client_access_token",
        "refresh_token": "client_refresh_token",
        "expires_in": 3600
    }
    response = await async_client.post("/api/v1/integrations/spotify/sync", headers=headers, json=payload)

    assert response.status_code == 200
    assert response.json()["success"] is True

    # 3. Verify DB record
    integration = session.query(Integration).filter(
        Integration.user_id == user_id,
        Integration.service == "spotify"
    ).first()
    assert integration is not None
    assert integration.is_active is True
    assert integration.access_token == "client_access_token"

@pytest.mark.asyncio
async def test_spotify_playback_endpoint_not_connected(async_client: AsyncClient, mock_supabase_auth):
    # Mock user but no integration in DB
    mock_supabase_auth.get_user.return_value = {
        "id": "test_user_no_spotify",
        "email": "test@example.com"
    }

    headers = {"Authorization": "Bearer test_token"}
    response = await async_client.get("/api/v1/integrations/spotify/playback", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Spotify not connected"

@pytest.mark.asyncio
async def test_spotify_playback_success(async_client: AsyncClient, mock_supabase_auth, session: Session):
    # 1. Setup User and Integration in DB
    user_id = "test_user_with_spotify"
    
    db_user = User(
        id=user_id,
        email="test@example.com",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(db_user)
    
    integration = Integration(
        id=str(uuid.uuid4()),
        user_id=user_id,
        service="spotify",
        access_token="valid_access_token",
        refresh_token="valid_refresh_token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_active=True
    )
    session.add(integration)
    session.flush() # Use flush instead of commit

    mock_supabase_auth.get_user.return_value = {
        "id": user_id,
        "email": "test@example.com"
    }

    # 2. Mock Spotify Client Service
    # We need to patch app.routers.integrations.integrations_spotify.spotify_client
    with patch("app.routers.integrations.integrations_spotify.spotify_client") as mock_spotify:
        mock_spotify.get_valid_token = AsyncMock(return_value="valid_access_token")
        mock_spotify.get_current_playback = AsyncMock(return_value={
            "is_playing": True,
            "item": {"name": "Test Song", "uri": "spotify:track:123"}
        })
        mock_spotify.play = AsyncMock()
        mock_spotify.pause = AsyncMock()
        mock_spotify.skip_next = AsyncMock()

        headers = {"Authorization": "Bearer test_token"}
        
        # Test Get Playback
        response = await async_client.get("/api/v1/integrations/spotify/playback", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_playing"] is True
        assert data["item"]["name"] == "Test Song"

        # Test Play
        response = await async_client.post("/api/v1/integrations/spotify/play?uri=spotify:track:123", headers=headers)
        assert response.status_code == 200
        mock_spotify.play.assert_called_once()

        # Test Pause
        response = await async_client.post("/api/v1/integrations/spotify/pause", headers=headers)
        assert response.status_code == 200
        mock_spotify.pause.assert_called_once()
        
        # Test Next
        response = await async_client.post("/api/v1/integrations/spotify/next", headers=headers)
        assert response.status_code == 200
        mock_spotify.skip_next.assert_called_once()
