"""Health and root metadata routes."""

from fastapi import APIRouter

from kaji_serve import __version__
from kaji_serve.config import settings

router = APIRouter(tags=["health"])


def health_payload() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": __version__,
    }


def root_payload() -> dict[str, str]:
    return {
        "message": settings.PROJECT_NAME,
        "version": __version__,
        "docs": f"{settings.API_V1_PREFIX}/docs",
        "health": "/health",
    }


@router.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers."""
    return health_payload()


@router.get("/")
async def root():
    """Root endpoint with API information."""
    return root_payload()
