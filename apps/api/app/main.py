"""Main FastAPI application."""

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.broker import broker
from app.core.database import close_async_engine
from app.core.redis import close_redis_client
from app.services.integrations.token_migration import (
    migrate_plaintext_integration_tokens,
)
from app.services.integrations.spotify import spotify_client
from app.services.lifecycle import close_registered_services
from app.services.integrations.workspace.auth import close_workspace_http_client
from app.routers.integrations.integrations_shared import close_oauth_http_client
from app.routers import (
    integrations,
    routers_auth,
    routers_gemini,
    routers_stt,
    routers_tools,
)

# Configure Rich logging
setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await migrate_plaintext_integration_tokens()
    await broker.startup()

    yield

    # Shutdown
    await broker.shutdown()
    await close_async_engine()
    await close_oauth_http_client()
    await spotify_client.close()
    await close_registered_services()
    await close_workspace_http_client()
    await close_redis_client()


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    version="1.0.0",
    description="Modal API",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("Configured CORS origins", extra={"origins": settings.cors_allow_origins})

# Include routers
app.include_router(routers_auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations.router, prefix=settings.API_V1_PREFIX)
app.include_router(routers_stt.router, prefix=settings.API_V1_PREFIX)
app.include_router(routers_gemini.router, prefix=settings.API_V1_PREFIX)
app.include_router(routers_tools.router, prefix=settings.API_V1_PREFIX)

logger.info("Starting %s", settings.PROJECT_NAME)


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers."""
    logger.debug("Health check requested")
    return {"status": "healthy", "service": settings.PROJECT_NAME, "version": "1.0.0"}


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": settings.PROJECT_NAME,
        "version": "1.0.0",
        "docs": f"{settings.API_V1_PREFIX}/docs",
        "health": "/health",
    }
