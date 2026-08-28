"""Main FastAPI application."""

import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from kaji_serve import __version__
from kaji_serve.config import settings
from kaji_serve.server.router import api_router
from kaji.core.safe_logging import log_redacted_failure
from kaji.runtime.providers.errors import ProviderError
from kaji_serve.server.database import close_async_engine
from kaji_serve.server.errors import (
    ServiceError,
    provider_error_to_detail,
    provider_error_to_http_status,
    service_error_to_detail,
    service_error_to_http_status,
)
from kaji_serve.server.lifecycle import close_registered_services
from kaji_serve.server.logging import setup_logging
from kaji_serve.server.v1.health import health_payload, root_payload

setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_async_engine()
    await close_registered_services()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    version=__version__,
    description="Kaji reference service",
    lifespan=lifespan,
)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    log_redacted_failure(
        logger,
        logging.WARNING,
        "External service request failed",
        exc,
        identifiers={"path": request.url.path},
    )
    return JSONResponse(
        status_code=service_error_to_http_status(exc),
        content={"detail": service_error_to_detail(exc, fallback="Service error")},
    )


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError):
    log_redacted_failure(
        logger,
        logging.WARNING,
        "Model provider request failed",
        exc,
        identifiers={"path": request.url.path},
    )
    return JSONResponse(
        status_code=provider_error_to_http_status(exc),
        content={"detail": provider_error_to_detail(exc, fallback="Provider error")},
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
    return health_payload()


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return root_payload()
