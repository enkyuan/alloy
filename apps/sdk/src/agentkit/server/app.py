"""Main FastAPI application."""

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from agentkit.server.router import api_router
from agentkit.core.config import settings
from agentkit.core.logging import setup_logging
from agentkit.core.broker import broker
from agentkit.core.database import close_async_engine
from agentkit.core.redis import close_redis_client
from agentkit.core.lifecycle import close_registered_services
from agentkit.providers.errors import (
    ServiceError,
    service_error_to_detail,
    service_error_to_http_status,
)

setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.startup()
    yield
    await broker.shutdown()
    await close_async_engine()
    await close_registered_services()
    await close_redis_client()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    version="1.0.0",
    description="AgentKit SDK",
    lifespan=lifespan,
)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    logger.warning("External service error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=service_error_to_http_status(exc),
        content={"detail": service_error_to_detail(exc, fallback="Service error")},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("Configured CORS origins", extra={"origins": settings.cors_allow_origins})

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

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
