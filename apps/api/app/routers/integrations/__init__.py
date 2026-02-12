"""Integration router package."""

from fastapi import APIRouter

from .integrations_calendly import router as calendly_router
from .integrations_discord import router as discord_router
from .integrations_google import router as google_router
from .integrations_management import router as management_router
from .integrations_spotify import router as spotify_router
from .integrations_todoist import router as todoist_router

router = APIRouter()
router.include_router(spotify_router, prefix="/integrations", tags=["integrations"])
router.include_router(management_router, prefix="/integrations", tags=["integrations"])
router.include_router(google_router, prefix="/integrations", tags=["integrations"])
router.include_router(discord_router, prefix="/integrations", tags=["integrations"])
router.include_router(todoist_router, prefix="/integrations", tags=["integrations"])
router.include_router(calendly_router, prefix="/integrations", tags=["integrations"])
