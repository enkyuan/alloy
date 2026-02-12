"""Google Calendar API service for calendar operations."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GoogleCalendarService:
    """Service for Google Calendar API operations."""

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        """Initialize Google Calendar service with OAuth credentials.

        Args:
            access_token: OAuth2 access token
            refresh_token: OAuth2 refresh token (optional)
        """
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
        )
        self.service = build("calendar", "v3", credentials=self.credentials)

    def list_events(
        self,
        calendar_id: str = "primary",
        max_results: int = 10,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List upcoming events from a calendar.

        Args:
            calendar_id: Calendar ID (default: 'primary')
            max_results: Maximum number of events to return
            time_min: Minimum time for events (default: now)
            time_max: Maximum time for events (optional)

        Returns:
            List of event objects

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            if time_min is None:
                time_min = datetime.now(timezone.utc)

            params = {
                "calendarId": calendar_id,
                "timeMin": time_min.isoformat() + "Z",
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }

            if time_max:
                params["timeMax"] = time_max.isoformat() + "Z"

            events_result = self.service.events().list(**params).execute()
            events = events_result.get("items", [])

            logger.info(f"Retrieved {len(events)} events from calendar")
            return events

        except HttpError as error:
            logger.error(f"Failed to list events: {error}")
            raise

    def get_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        """Get details of a specific event.

        Args:
            event_id: Event ID
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Event object

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )

            logger.info(f"Retrieved event: {event.get('summary', 'Untitled')}")
            return event

        except HttpError as error:
            logger.error(f"Failed to get event: {error}")
            raise

    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[List[str]] = None,
        recurrence: Optional[List[str]] = None,
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        """Create a new calendar event.

        Args:
            summary: Event title
            start_time: Event start time
            end_time: Event end time
            description: Event description (optional)
            location: Event location (optional)
            attendees: List of attendee email addresses (optional)
            recurrence: List of RRULE strings (optional)
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Created event object

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            event: Dict[str, Any] = {
                "summary": summary,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": "UTC",
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": "UTC",
                },
            }

            if description:
                event["description"] = description

            if location:
                event["location"] = location

            if attendees:
                event["attendees"] = [{"email": email} for email in attendees]

            if recurrence:
                event["recurrence"] = recurrence

            if description:
                event["description"] = description

            if location:
                event["location"] = location

            if attendees:
                event["attendees"] = [{"email": email} for email in attendees]

            created_event = (
                self.service.events()
                .insert(calendarId=calendar_id, body=event)
                .execute()
            )

            logger.info(f"Created event: {created_event.get('summary', 'Untitled')}")
            return created_event

        except HttpError as error:
            logger.error(f"Failed to create event: {error}")
            raise

    def update_event(
        self,
        event_id: str,
        summary: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        """Update an existing calendar event.

        Args:
            event_id: Event ID to update
            summary: New event title (optional)
            start_time: New start time (optional)
            end_time: New end time (optional)
            description: New description (optional)
            location: New location (optional)
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Updated event object

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            # Get existing event
            event = (
                self.service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )

            # Update fields if provided
            if summary:
                event["summary"] = summary

            if start_time:
                event["start"] = {
                    "dateTime": start_time.isoformat(),
                    "timeZone": "UTC",
                }

            if end_time:
                event["end"] = {
                    "dateTime": end_time.isoformat(),
                    "timeZone": "UTC",
                }

            if description is not None:
                event["description"] = description

            if location is not None:
                event["location"] = location

            updated_event = (
                self.service.events()
                .update(calendarId=calendar_id, eventId=event_id, body=event)
                .execute()
            )

            logger.info(f"Updated event: {updated_event.get('summary', 'Untitled')}")
            return updated_event

        except HttpError as error:
            logger.error(f"Failed to update event: {error}")
            raise

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        """Delete a calendar event.

        Args:
            event_id: Event ID to delete
            calendar_id: Calendar ID (default: 'primary')

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            self.service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()

            logger.info(f"Deleted event: {event_id}")

        except HttpError as error:
            logger.error(f"Failed to delete event: {error}")
            raise

    def list_calendars(self) -> List[Dict[str, Any]]:
        """List all calendars accessible to the user.

        Returns:
            List of calendar objects

        Raises:
            HttpError: If Calendar API request fails
        """
        try:
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get("items", [])

            logger.info(f"Retrieved {len(calendars)} calendars")
            return calendars

        except HttpError as error:
            logger.error(f"Failed to list calendars: {error}")
            raise

    def get_upcoming_events(
        self, days: int = 7, max_results: int = 10, calendar_id: str = "primary"
    ) -> List[Dict[str, Any]]:
        """Get upcoming events for the next N days.

        Args:
            days: Number of days to look ahead (default: 7)
            max_results: Maximum number of events to return
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            List of upcoming event objects

        Raises:
            HttpError: If Calendar API request fails
        """
        time_min = datetime.now(timezone.utc)
        time_max = time_min + timedelta(days=days)

        return self.list_events(
            calendar_id=calendar_id,
            max_results=max_results,
            time_min=time_min,
            time_max=time_max,
        )

    def get_today_events(self, calendar_id: str = "primary") -> List[Dict[str, Any]]:
        """Get events for today.

        Args:
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            List of today's event objects

        Raises:
            HttpError: If Calendar API request fails
        """
        now = datetime.now(timezone.utc)
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=1)

        return self.list_events(
            calendar_id=calendar_id,
            max_results=50,
            time_min=time_min,
            time_max=time_max,
        )

    def check_free_busy(
        self,
        time_min: datetime,
        time_max: datetime,
        items: List[Dict[str, str]] = [{"id": "primary"}],
    ) -> Dict[str, Any]:
        """Check free/busy status for calendars.

        Args:
            time_min: Start of check period
            time_max: End of check period
            items: List of calendar IDs to check (default: primary)

        Returns:
            Free/busy information
        """
        try:
            body = {
                "timeMin": time_min.isoformat() + "Z",
                "timeMax": time_max.isoformat() + "Z",
                "items": items,
            }
            result = self.service.freebusy().query(body=body).execute()
            logger.info("Checked free/busy status")
            return result
        except HttpError as error:
            logger.error(f"Failed to check free/busy: {error}")
            raise

    def patch_event(
        self,
        event_id: str,
        body: Dict[str, Any],
        calendar_id: str = "primary",
    ) -> Dict[str, Any]:
        """Patch an existing event (partial update).

        Args:
            event_id: Event ID
            body: Dictionary of fields to update
            calendar_id: Calendar ID (default: 'primary')

        Returns:
            Updated event object
        """
        try:
            updated_event = (
                self.service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=body)
                .execute()
            )
            logger.info(f"Patched event: {event_id}")
            return updated_event
        except HttpError as error:
            logger.error(f"Failed to patch event: {error}")
            raise


# Singleton instance that can be initialized per-request
google_calendar_service: Optional[GoogleCalendarService] = None


def get_google_calendar_service(
    access_token: str, refresh_token: Optional[str] = None
) -> GoogleCalendarService:
    """Factory function to create Google Calendar service instance.

    Args:
        access_token: OAuth2 access token
        refresh_token: OAuth2 refresh token (optional)

    Returns:
        Configured GoogleCalendarService instance
    """
    return GoogleCalendarService(access_token=access_token, refresh_token=refresh_token)
