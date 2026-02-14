"""Google workspace integration route aggregator."""

from fastapi import APIRouter

from .integrations_google_calendar import router as google_calendar_router
from .integrations_google_gmail import router as gmail_router

router = APIRouter()
router.include_router(gmail_router)
router.include_router(google_calendar_router)
