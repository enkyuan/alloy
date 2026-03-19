import os
import sys
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
import fakeredis.aioredis
# Ensure app can be imported
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch, AsyncMock


from app.main import app
from app.core.database import Base, get_db
from app.core.redis import get_redis_client

# Postgres Connection Configuration
# We use the local exposed port 5432 from docker-compose
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
TEST_DB_NAME = "modal_test_db"
ADMIN_DB_NAME = "postgres"

TEST_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
ADMIN_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{ADMIN_DB_NAME}"

@pytest.fixture(scope="session")
def db_engine():
    """Create a test database and provide its engine."""
    # 1. Connect to admin DB to create test DB
    admin_engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            # Terminate existing connections to test db if any (to allow drop)
            conn.execute(text(f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{TEST_DB_NAME}'
                AND pid <> pg_backend_pid();
            """))
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    except Exception as e:
        print(f"Error initializing test database: {e}")
        # Proceeding might fail if DB creation failed, but let's try
    finally:
        admin_engine.dispose()

    # 2. Connect to Test DB and setup schema
    engine = create_engine(TEST_DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        
        yield engine
        
    finally:
        # Teardown
        engine.dispose()
        # Optional: Drop DB after tests (commented out to allow debugging if tests fail)
        # admin_engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
        # with admin_engine.connect() as conn:
        #     conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        # admin_engine.dispose()

@pytest.fixture(name="session")
def session_fixture(db_engine):
    """Provide a transactional session. Rollback after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = TestingSessionLocal()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(name="async_client")
async def async_client_fixture(session) -> AsyncGenerator:
    """Provide an async client with overridden dependencies."""
    
    # Override Redis with FakeRedis
    fake_redis = fakeredis.aioredis.FakeRedis()
    async def override_get_redis():
        return fake_redis
    
    # Override DB with test session
    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_redis_client] = override_get_redis
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()

@pytest.fixture(name="test_client")
def test_client_fixture(session):
    """Provide a synchronous TestClient for WebSocket tests."""
    
    # Override Redis with FakeRedis
    fake_redis = fakeredis.aioredis.FakeRedis()
    async def override_get_redis():
        return fake_redis
    
    # Override DB with test session
    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_redis_client] = override_get_redis
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client
    
    app.dependency_overrides.clear()

@pytest.fixture
def mock_supabase_auth():
    """
    Mock the supabase_auth_service singleton methods.
    We modify the instance directly because it is imported in many places
    and patching the variable in one module won't affect others that already imported it.
    """
    from app.services.user.auth import supabase_auth_service

    # Save original methods
    original_get_user = supabase_auth_service.get_user
    original_refresh_token = supabase_auth_service.refresh_token

    # Create mocks
    mock_get = AsyncMock()
    mock_refresh = AsyncMock()

    # Apply mocks
    supabase_auth_service.get_user = mock_get
    supabase_auth_service.refresh_token = mock_refresh

    # Yield the service (or the mocks if preferred, but tests access .get_user on the service)
    # To match usage: mock_supabase_auth.get_user.return_value = ...
    # We can yield a simple object holder if we want, or just yield the service
    # which has the mocks attached.
    # The tests use `mock_supabase_auth.get_user`, so yielding the service works
    # because `supabase_auth_service.get_user` IS the mock.
    yield supabase_auth_service

    # Restore original methods
    supabase_auth_service.get_user = original_get_user
    supabase_auth_service.refresh_token = original_refresh_token
