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
            token_uri="https://oauth2.googleapis.com/token"
        )
        self.service = build('gmail', 'v1', credentials=self.credentials)

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None
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
            message['to'] = to
            message['subject'] = subject
            if from_email:
                message['from'] = from_email

            # Encode message
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            create_message = {'raw': encoded_message}

            # Send message
            send_result = self.service.users().messages().send(
                userId='me',
                body=create_message
            ).execute()

            logger.info(f"Email sent successfully: {send_result['id']}")
            return send_result

        except HttpError as error:
            logger.error(f"Failed to send email: {error}")
            raise

    def get_messages(
        self,
        max_results: int = 10,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None
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
            request_params = {
                'userId': 'me',
                'maxResults': max_results
            }
            
            if query:
                request_params['q'] = query
            if label_ids:
                request_params['labelIds'] = label_ids

            results = self.service.users().messages().list(**request_params).execute()
            messages = results.get('messages', [])

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
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

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
            results = self.service.users().messages().list(
                userId='me',
                q='is:unread',
                labelIds=['INBOX']
            ).execute()

            count = results.get('resultSizeEstimate', 0)
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
            message = self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()

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
            profile = self.service.users().getProfile(userId='me').execute()
            logger.info(f"Retrieved Gmail profile: {profile.get('emailAddress')}")
            return profile

        except HttpError as error:
            logger.error(f"Failed to get Gmail profile: {error}")
            raise

    def get_recent_emails(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """Get recent emails with parsed headers for voice responses.
        
        Args:
            max_results: Maximum number of emails to return
            
        Returns:
            List of emails with parsed from, subject, and snippet
            
        Raises:
            HttpError: If Gmail API request fails
        """
        try:
            # Get recent messages from inbox
            messages = self.get_messages(
                max_results=max_results,
                label_ids=['INBOX']
            )
            
            recent_emails = []
            
            for message in messages:
                try:
                    # Get full message details
                    message_detail = self.get_message_detail(message['id'])
                    
                    # Parse headers
                    headers = message_detail.get('payload', {}).get('headers', [])
                    from_header = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
                    subject_header = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No subject')
                    
                    # Extract sender name from "Name <email>" format
                    sender_name = from_header
                    if '<' in from_header:
                        sender_name = from_header.split('<')[0].strip().strip('"')
                    
                    recent_emails.append({
                        'id': message['id'],
                        'from': sender_name,
                        'subject': subject_header,
                        'snippet': message_detail.get('snippet', ''),
                        'thread_id': message_detail.get('threadId', '')
                    })
                    
                except Exception as e:
                    logger.warning(f"Failed to parse message {message['id']}: {str(e)}")
                    continue
            
            logger.info(f"Retrieved {len(recent_emails)} recent emails")
            return recent_emails
            
        except HttpError as error:
            logger.error(f"Failed to get recent emails: {error}")
            raise


# Singleton instance that can be initialized per-request
gmail_service: Optional[GmailService] = None


def get_gmail_service(access_token: str, refresh_token: Optional[str] = None) -> GmailService:
    """Factory function to create Gmail service instance.
    
    Args:
        access_token: OAuth2 access token
        refresh_token: OAuth2 refresh token (optional)
        
    Returns:
        Configured GmailService instance
    """
    return GmailService(access_token=access_token, refresh_token=refresh_token)
