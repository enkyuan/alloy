import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.broker import broker
from app.core.database import AsyncSessionLocal
from app.models.integration import Integration
from app.services.integrations.workspace.auth import get_valid_google_token
from app.services.integrations.workspace.gcalendar import get_google_calendar_service
from app.services.integrations.workspace.gmail import get_gmail_service

logger = logging.getLogger(__name__)


async def get_integration(
    db: AsyncSession, user_id: str, service_name: str
) -> Integration | None:
    """Get active integration for a user/service."""
    query = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.service == service_name,
            Integration.is_active.is_(True),
        )
    )
    return query.scalar_one_or_none()


@broker.task(task_name="workspace.summarize_emails")
async def summarize_emails(user_id: str, count: int = 5) -> str:
    """Summarize recent emails for the user."""
    logger.info(f"Summarizing last {count} emails for {user_id}")

    try:
        async with AsyncSessionLocal() as db:
            integration = await get_integration(db, user_id, "gmail")
            if not integration:
                return "Gmail is not connected. Please connect it in settings."

            token = await get_valid_google_token(integration, db)

        service = get_gmail_service(token)
        messages = await asyncio.to_thread(service.get_messages, max_results=count)
        if not messages:
            return "No recent emails found."

        async def fetch_detail(msg_id: str):
            return await asyncio.to_thread(service.get_message_detail, msg_id)

        detail_tasks = [fetch_detail(msg["id"]) for msg in messages]
        details = await asyncio.gather(*detail_tasks)

        summary_lines: List[str] = []
        for msg in details:
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "(No Subject)")
            sender = headers.get("From", "(Unknown)")
            summary_lines.append(f"- {subject} (from {sender})")

        summary = f"Here are your last {len(messages)} emails:\n" + "\n".join(summary_lines)
        logger.info(f"Emails summarized for {user_id}")
        return summary
    except Exception as e:
        logger.error(f"Failed to summarize emails for {user_id}: {e}", exc_info=True)
        return f"Failed to summarize emails: {str(e)}"


@broker.task(task_name="workspace.check_schedule")
async def check_schedule(user_id: str) -> str:
    """Check today's schedule."""
    logger.info(f"Checking schedule for {user_id}")

    try:
        async with AsyncSessionLocal() as db:
            integration = await get_integration(db, user_id, "google_calendar")
            if not integration:
                return "Google Calendar is not connected. Please connect it in settings."

            token = await get_valid_google_token(integration, db)

        service = get_google_calendar_service(token)
        events = await asyncio.to_thread(service.get_today_events)
        if not events:
            return "You have no meetings scheduled for today."

        event_lines: List[str] = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            summary = event.get("summary", "(No Title)")
            time_str = (
                datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%I:%M %p")
                if "T" in start
                else "All Day"
            )
            event_lines.append(f"- {time_str}: {summary}")

        result = f"You have {len(events)} meetings today:\n" + "\n".join(event_lines)
        logger.info(f"Schedule checked for {user_id}")
        return result
    except Exception as e:
        logger.error(f"Failed to check schedule for {user_id}: {e}", exc_info=True)
        return f"Failed to check schedule: {str(e)}"


@broker.task(task_name="workspace.create_meeting")
async def create_meeting(
    user_id: str, summary: str, start_time: str, duration_minutes: int = 60
) -> str:
    """Create a meeting on the user's calendar."""
    logger.info(f"Creating meeting '{summary}' for {user_id}")

    try:
        async with AsyncSessionLocal() as db:
            integration = await get_integration(db, user_id, "google_calendar")
            if not integration:
                return "Google Calendar is not connected."

            token = await get_valid_google_token(integration, db)

        service = get_google_calendar_service(token)
        try:
            start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            return "Invalid date format. Please use ISO format."

        end = start + timedelta(minutes=duration_minutes)
        await asyncio.to_thread(service.create_event, summary, start, end)

        result = f"Created meeting '{summary}' at {start.strftime('%I:%M %p')}"
        logger.info(f"Meeting created for {user_id}")
        return result
    except Exception as e:
        logger.error(f"Failed to create meeting for {user_id}: {e}", exc_info=True)
        return f"Failed to create meeting: {str(e)}"
