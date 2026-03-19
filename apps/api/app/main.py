"""Main FastAPI application."""

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
<<<<<<< HEAD
from app.routers import auth, integrations, stt, gemini
from app.core.event_backbone import event_backbone
from app.core.taskiq import broker
from app.workers.consumer import start_stream_consumer
=======
from app.core.broker import broker
from app.core.database import close_async_engine
from app.core.redis import close_redis_client
from app.services.integrations.token_migration import (
    migrate_plaintext_integration_tokens,
)
from app.services.integrations.errors import (
    IntegrationServiceError,
    integration_error_to_http_status,
    integration_error_to_detail,
)
from app.services.lifecycle import close_registered_services
from app.routers import (
    integrations,
    routers_auth,
    routers_gemini,
    routers_stt,
    routers_tools,
)
>>>>>>> codex/refactor

# Configure Rich logging
setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
<<<<<<< HEAD
    await event_backbone.connect()
    await broker.startup()

    # Start consumer in background
    consumer_task = asyncio.create_task(start_stream_consumer())

=======
    await migrate_plaintext_integration_tokens()
    await broker.startup()

>>>>>>> codex/refactor
    yield

    # Shutdown
    await broker.shutdown()
<<<<<<< HEAD
    await event_backbone.close()
=======
    await close_async_engine()
    await close_registered_services()
    await close_redis_client()
>>>>>>> codex/refactor


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

@app.exception_handler(IntegrationServiceError)
async def integration_service_error_handler(request: Request, exc: IntegrationServiceError):
    logger.warning("Integration service error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=integration_error_to_http_status(exc),
        content={"detail": integration_error_to_detail(exc, fallback="Integration service error")}
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
