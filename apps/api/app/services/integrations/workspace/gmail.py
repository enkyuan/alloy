"""Gmail API service for email operations."""

import base64
import logging
from email.mime.text import MIMEText
from typing import Optional, List, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GmailService:
    """Service for Gmail API operations."""

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        """Initialize Gmail service with OAuth credentials.

        Args:
            access_token: OAuth2 access token
            refresh_token: OAuth2 refresh token (optional)
        """
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
        )
        self.service = build("gmail", "v1", credentials=self.credentials)

    def send_email(
        self, to: str, subject: str, body: str, from_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send an email via Gmail API.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            from_email: Sender email (defaults to authenticated user)

        Returns:
            Message metadata from Gmail API

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            if from_email:
                message["from"] = from_email

            # Encode message
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {"raw": encoded_message}

            # Send message
            send_result = (
                self.service.users()
                .messages()
                .send(userId="me", body=create_message)
                .execute()
            )

            logger.info(f"Email sent successfully: {send_result['id']}")
            return send_result

        except HttpError as error:
            logger.error(f"Failed to send email: {error}")
            raise

    def get_messages(
        self,
        max_results: int = 10,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get list of messages from Gmail.

        Args:
            max_results: Maximum number of messages to return
            query: Gmail search query (e.g., "is:unread")
            label_ids: List of label IDs to filter by (e.g., ["INBOX"])

        Returns:
            List of message metadata

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            request_params: Dict[str, Any] = {"userId": "me", "maxResults": max_results}

            if query:
                request_params["q"] = query
            if label_ids:
                request_params["labelIds"] = label_ids

            results = self.service.users().messages().list(**request_params).execute()
            messages = results.get("messages", [])

            logger.info(f"Retrieved {len(messages)} messages")
            return messages

        except HttpError as error:
            logger.error(f"Failed to get messages: {error}")
            raise

    def get_message_detail(self, message_id: str) -> Dict[str, Any]:
        """Get full details of a specific message.

        Args:
            message_id: Gmail message ID

        Returns:
            Full message data including headers and body

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            logger.info(f"Retrieved message detail: {message_id}")
            return message

        except HttpError as error:
            logger.error(f"Failed to get message detail: {error}")
            raise

    def get_unread_count(self) -> int:
        """Get count of unread messages in inbox.

        Returns:
            Number of unread messages

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread", labelIds=["INBOX"])
                .execute()
            )

            count = results.get("resultSizeEstimate", 0)
            logger.info(f"Unread message count: {count}")
            return count

        except HttpError as error:
            logger.error(f"Failed to get unread count: {error}")
            raise

    def mark_as_read(self, message_id: str) -> Dict[str, Any]:
        """Mark a message as read.

        Args:
            message_id: Gmail message ID

        Returns:
            Updated message metadata

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            message = (
                self.service.users()
                .messages()
                .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
                .execute()
            )

            logger.info(f"Marked message as read: {message_id}")
            return message

        except HttpError as error:
            logger.error(f"Failed to mark message as read: {error}")
            raise

    def get_profile(self) -> Dict[str, Any]:
        """Get the authenticated user's Gmail profile.

        Returns:
            User profile with email address and other metadata

        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            profile = self.service.users().getProfile(userId="me").execute()
            logger.info(f"Retrieved Gmail profile: {profile.get('emailAddress')}")
            return profile

        except HttpError as error:
            logger.error(f"Failed to get Gmail profile: {error}")
            raise

    def create_draft(
        self, to: str, subject: str, body: str, from_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a draft email.

        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            from_email: Sender email (optional)

        Returns:
            Draft object from Gmail API
        """
        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            if from_email:
                message["from"] = from_email

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {"message": {"raw": encoded_message}}

            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body=create_message)
                .execute()
            )

            logger.info(f"Created draft: {draft['id']}")
            return draft

        except HttpError as error:
            logger.error(f"Failed to create draft: {error}")
            raise

    def update_draft(
        self,
        draft_id: str,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update an existing draft.

        Args:
            draft_id: Draft ID to update
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            from_email: Sender email (optional)

        Returns:
            Updated draft object
        """
        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            if from_email:
                message["from"] = from_email

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            update_message = {"message": {"raw": encoded_message}}

            draft = (
                self.service.users()
                .drafts()
                .update(userId="me", id=draft_id, body=update_message)
                .execute()
            )

            logger.info(f"Updated draft: {draft_id}")
            return draft

        except HttpError as error:
            logger.error(f"Failed to update draft: {error}")
            raise

    def send_draft(self, draft_id: str) -> Dict[str, Any]:
        """Send a draft.

        Args:
            draft_id: Draft ID to send

        Returns:
            Sent message object
        """
        try:
            result = (
                self.service.users()
                .drafts()
                .send(userId="me", body={"id": draft_id})
                .execute()
            )

            logger.info(f"Sent draft: {draft_id}")
            return result

        except HttpError as error:
            logger.error(f"Failed to send draft: {error}")
            raise

    def list_labels(self) -> List[Dict[str, Any]]:
        """List all labels in the user's mailbox.

        Returns:
            List of label objects
        """
        try:
            results = self.service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            logger.info(f"Retrieved {len(labels)} labels")
            return labels
        except HttpError as error:
            logger.error(f"Failed to list labels: {error}")
            raise

    def get_label(self, label_id: str) -> Dict[str, Any]:
        """Get details of a specific label.

        Args:
            label_id: Label ID

        Returns:
            Label object
        """
        try:
            label = (
                self.service.users().labels().get(userId="me", id=label_id).execute()
            )
            return label
        except HttpError as error:
            logger.error(f"Failed to get label: {error}")
            raise

    def create_label(
        self,
        name: str,
        label_list_visibility: str = "labelShow",
        message_list_visibility: str = "show",
    ) -> Dict[str, Any]:
        """Create a new label.

        Args:
            name: Label name
            label_list_visibility: Visibility in label list (labelShow, labelHide)
            message_list_visibility: Visibility in message list (show, hide)

        Returns:
            Created label object
        """
        try:
            label_object = {
                "name": name,
                "labelListVisibility": label_list_visibility,
                "messageListVisibility": message_list_visibility,
            }
            label = (
                self.service.users()
                .labels()
                .create(userId="me", body=label_object)
                .execute()
            )
            logger.info(f"Created label: {name}")
            return label
        except HttpError as error:
            logger.error(f"Failed to create label: {error}")
            raise

    def get_thread(self, thread_id: str) -> Dict[str, Any]:
        """Get a specific email thread.

        Args:
            thread_id: Thread ID

        Returns:
            Thread object with messages
        """
        try:
            thread = (
                self.service.users().threads().get(userId="me", id=thread_id).execute()
            )
            logger.info(f"Retrieved thread: {thread_id}")
            return thread
        except HttpError as error:
            logger.error(f"Failed to get thread: {error}")
            raise


# Singleton instance that can be initialized per-request
gmail_service: Optional[GmailService] = None


def get_gmail_service(
    access_token: str, refresh_token: Optional[str] = None
) -> GmailService:
    """Factory function to create Gmail service instance.

    Args:
        access_token: OAuth2 access token
        refresh_token: OAuth2 refresh token (optional)

    Returns:
        Configured GmailService instance
    """
    return GmailService(access_token=access_token, refresh_token=refresh_token)
