"""Main FastAPI application."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging import setup_logging
from app.routers import auth, integrations, stt, gemini

# Configure Rich logging
setup_logging(debug=settings.DEBUG)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    version="1.0.0",
    description="Modal API",
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
