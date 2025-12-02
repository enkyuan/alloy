import asyncio
import logging
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from app.services.workspace.gmail import GmailService
from app.services.workspace.gcalendar import GoogleCalendarService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def verify_workspace_services():
    logger.info("Starting workspace services verification...")

    # Mock credentials
    mock_creds = MagicMock()

    # 1. Verify Gmail Enhancements
    logger.info("Verifying Gmail Service...")
    with patch("app.services.workspace.gmail.build") as mock_build:
        service = GmailService("fake_token")
        mock_gmail = mock_build.return_value

        # Test Create Draft
        service.create_draft("test@example.com", "Subject", "Body")
        mock_gmail.users().drafts().create.assert_called()
        logger.info("[SUCCESS] Gmail: create_draft")

        # Test List Labels
        service.list_labels()
        mock_gmail.users().labels().list.assert_called()
        logger.info("[SUCCESS] Gmail: list_labels")

    # 2. Verify Calendar Enhancements
    logger.info("Verifying Calendar Service...")
    with patch("app.services.workspace.gcalendar.build") as mock_build:
        service = GoogleCalendarService("fake_token")
        mock_calendar = mock_build.return_value

        # Test Create Event with Recurrence
        start = datetime.utcnow()
        end = start + timedelta(hours=1)
        service.create_event(
            "Meeting", start, end, recurrence=["RRULE:FREQ=WEEKLY;COUNT=10"]
        )
        # Verify recurrence was passed in body
        call_args = mock_calendar.events().insert.call_args[1]
        assert "recurrence" in call_args["body"]
        logger.info("[SUCCESS] Calendar: create_event with recurrence")

        # Test Free/Busy
        service.check_free_busy(start, end)
        mock_calendar.freebusy().query.assert_called()
        logger.info("[SUCCESS] Calendar: check_free_busy")

    logger.info("Verification complete.")


if __name__ == "__main__":
    asyncio.run(verify_workspace_services())
