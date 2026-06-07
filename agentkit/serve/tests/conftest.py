import os
import sys

# Provide safe defaults for required settings BEFORE importing the app, so that
# `agentkit.core.config.Settings()` (instantiated at import time) does not fail
# when these env vars are absent. Real values in the environment take precedence.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/agentkit_test_db",
)
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

import pytest
from typing import AsyncGenerator

from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from fastapi.testclient import TestClient
import fakeredis.aioredis

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock

from agentkit_serve.server.app import app
from agentkit.core.database import Base, get_db
from agentkit.core.redis import get_redis_client
from agentkit_serve.server.deps import get_current_supabase_user

DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
TEST_DB_NAME = "agentkit_test_db"
ADMIN_DB_NAME = "postgres"

TEST_DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
)
ASYNC_TEST_DATABASE_URL = TEST_DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://", 1
)
ADMIN_DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{ADMIN_DB_NAME}"
)


@pytest.fixture(scope="session")
def db_engine():
    """Create a test database and provide its sync engine for schema setup."""
    admin_engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    f"""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = '{TEST_DB_NAME}'
                AND pid <> pg_backend_pid();
            """
                )
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    except Exception as e:
        print(f"Error initializing test database: {e}")
    finally:
        admin_engine.dispose()

    engine = create_engine(TEST_DATABASE_URL)

    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        Base.metadata.create_all(bind=engine)

        yield engine

    finally:
        engine.dispose()


@pytest.fixture
async def async_db_engine(db_engine):
    """Async engine bound to the test database."""
    _ = db_engine
    engine = create_async_engine(
        ASYNC_TEST_DATABASE_URL,
        poolclass=NullPool,
    )
    yield engine
    await engine.dispose()


@pytest.fixture(name="session")
async def session_fixture(async_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Async SQLAlchemy session for tests and dependency overrides."""
    factory = async_sessionmaker(async_db_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()


@pytest.fixture(name="async_client")
async def async_client_fixture(session) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async client with overridden dependencies."""
    fake_redis = fakeredis.aioredis.FakeRedis()

    async def override_get_redis():
        return fake_redis

    async def override_get_db():
        yield session

    app.dependency_overrides[get_redis_client] = override_get_redis
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(name="test_client")
def test_client_fixture():
    """Provide a synchronous TestClient for WebSocket tests."""
    fake_redis = fakeredis.aioredis.FakeRedis()

    async def override_get_redis():
        return fake_redis

    app.dependency_overrides[get_redis_client] = override_get_redis

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_current_user():
    """Override JWT auth dependency with a fixed test user."""

    async def override_current_user() -> dict:
        return {
            "id": "test_user_id",
            "sub": "test_user_id",
            "email": "test@example.com",
        }

    app.dependency_overrides[get_current_supabase_user] = override_current_user
    yield override_current_user
    app.dependency_overrides.pop(get_current_supabase_user, None)


@pytest.fixture
def mock_supabase_auth():
    """Mock the supabase auth service at every consumption point.

    Two separate consumers, two separate patch targets:
    - agentkit_serve.server.v1.auth imports `supabase_auth_service` by name at
      module load (via __getattr__ shim → lru_cache singleton) — must patch the
      bound name in that module.
    - agentkit.modalities.voice.stt.handler calls get_supabase_auth_service()
      at call time — must patch the factory in that module's namespace.
    Both must point at the same mock object so tests see consistent state.
    """
    from unittest.mock import patch

    mock_svc = AsyncMock()
    mock_svc.get_user = AsyncMock()
    mock_svc.refresh_token = AsyncMock()

    with patch("agentkit_serve.server.v1.auth.supabase_auth_service", mock_svc), \
         patch("agentkit.modalities.voice.stt.handler.get_supabase_auth_service", return_value=mock_svc):
        yield mock_svc
