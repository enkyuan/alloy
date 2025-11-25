"""Main FastAPI application."""

import logging

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.routers import auth, integrations, stt, gemini
from app.core.kafka import kafka_service
from app.core.taskiq import broker
from app.workers.kafka import start_voice_input_consumer

# Configure Rich logging
setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await kafka_service.start()
    await broker.startup()

    # Start consumer in background
    consumer_task = asyncio.create_task(start_voice_input_consumer())

    yield

    # Shutdown
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await broker.shutdown()
    await kafka_service.stop()


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
    allow_origins=["*"],  # TODO: Update this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(integrations.router, prefix=settings.API_V1_PREFIX)
app.include_router(stt.router, prefix=settings.API_V1_PREFIX)
app.include_router(gemini.router, prefix=settings.API_V1_PREFIX)

logger.info(f"Starting {settings.PROJECT_NAME}")


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
