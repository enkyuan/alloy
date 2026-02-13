"""Todoist API service."""

from contextlib import asynccontextmanager
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import Integration

logger = logging.getLogger(__name__)


class TodoistService:
    """Service for Todoist API operations."""

    BASE_URL = settings.TODOIST_API_BASE_URL

    def __init__(self) -> None:
        self._http_client: Optional[httpx.AsyncClient] = None
        self._timeout = httpx.Timeout(10.0, connect=3.0)
        self._limits = httpx.Limits(
            max_connections=60,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=self._limits,
                follow_redirects=False,
            )
        return self._http_client

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[httpx.AsyncClient]:
        yield self._get_http_client()

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @staticmethod
    async def _commit(db: Session | AsyncSession) -> None:
        if isinstance(db, AsyncSession):
            await db.commit()
        else:
            db.commit()

    async def refresh_token(
        self, integration: Integration, db: Session | AsyncSession
    ) -> str:
        """Refresh Todoist access token.

        Note: Todoist tokens do not expire, so this method just updates
        our internal expiration timestamp to keep the integration active.

        Args:
            integration: Integration model
            db: Database session

        Returns:
            Current access token
        """
        # Todoist tokens don't expire, just extend the database timestamp
        # to prevent get_valid_token from complaining
        integration.expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)
        integration.updated_at = datetime.now(timezone.utc)

        await self._commit(db)

        logger.info(
            f"Successfully extended Todoist token validity for user {integration.user_id}"
        )
        return str(integration.access_token)

    async def get_valid_token(
        self, integration: Integration, db: Session | AsyncSession
    ) -> str:
        """Get valid access token.

        Args:
            integration: Integration model
            db: Database session

        Returns:
            Valid access token
        """
        # Todoist tokens don't expire, but check just in case
        if (
            integration.expires_at
            and integration.expires_at < datetime.now(timezone.utc) + timedelta(days=30)
        ):
            logger.info("Todoist token expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return str(integration.access_token)

    # ============================================================================
    # Projects
    # ============================================================================

    async def get_projects(self, access_token: str) -> List[Dict[str, Any]]:
        """Get all projects.

        Args:
            access_token: Valid Todoist access token

        Returns:
            List of projects

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/projects",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get projects: {response.text}")

            return response.json()

    async def get_project(self, access_token: str, project_id: str) -> Dict[str, Any]:
        """Get a specific project.

        Args:
            access_token: Valid Todoist access token
            project_id: Project ID

        Returns:
            Project details

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/projects/{project_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get project: {response.text}")

            return response.json()

    async def create_project(
        self,
        access_token: str,
        name: str,
        color: Optional[str] = None,
        parent_id: Optional[str] = None,
        is_favorite: bool = False,
    ) -> Dict[str, Any]:
        """Create a new project.

        Args:
            access_token: Valid Todoist access token
            name: Project name
            color: Project color
            parent_id: Parent project ID (for sub-projects)
            is_favorite: Whether to mark as favorite

        Returns:
            Created project

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {"name": name, "is_favorite": is_favorite}
        if color:
            data["color"] = color
        if parent_id:
            data["parent_id"] = parent_id

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/projects",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create project: {response.text}")

            return response.json()

    async def update_project(
        self,
        access_token: str,
        project_id: str,
        name: Optional[str] = None,
        color: Optional[str] = None,
        is_favorite: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update a project.

        Args:
            access_token: Valid Todoist access token
            project_id: Project ID
            name: New project name
            color: New project color
            is_favorite: Whether to mark as favorite

        Returns:
            Updated project

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if color is not None:
            data["color"] = color
        if is_favorite is not None:
            data["is_favorite"] = is_favorite

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/projects/{project_id}",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to update project: {response.text}")

            return response.json()

    async def delete_project(self, access_token: str, project_id: str) -> None:
        """Delete a project.

        Args:
            access_token: Valid Todoist access token
            project_id: Project ID

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.delete(
                f"{self.BASE_URL}/projects/{project_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to delete project: {response.text}")

    # ============================================================================
    # Tasks
    # ============================================================================

    async def get_tasks(
        self,
        access_token: str,
        project_id: Optional[str] = None,
        label: Optional[str] = None,
        filter_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get active tasks.

        Args:
            access_token: Valid Todoist access token
            project_id: Filter by project ID
            label: Filter by label
            filter_query: Todoist filter query

        Returns:
            List of tasks

        Raises:
            Exception: If API call fails
        """
        params = {}
        if project_id:
            params["project_id"] = project_id
        if label:
            params["label"] = label
        if filter_query:
            params["filter"] = filter_query

        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/tasks",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get tasks: {response.text}")

            return response.json()

    async def get_task(self, access_token: str, task_id: str) -> Dict[str, Any]:
        """Get a specific task.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID

        Returns:
            Task details

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get task: {response.text}")

            return response.json()

    async def create_task(
        self,
        access_token: str,
        content: str,
        description: Optional[str] = None,
        project_id: Optional[str] = None,
        due_string: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: int = 1,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a new task.

        Args:
            access_token: Valid Todoist access token
            content: Task content/title
            description: Task description
            project_id: Project ID
            due_string: Natural language due date (e.g., "tomorrow at 12pm")
            due_date: Due date in YYYY-MM-DD format
            priority: Priority (1-4, where 4 is urgent)
            labels: List of label names

        Returns:
            Created task

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {"content": content, "priority": priority}
        if description:
            data["description"] = description
        if project_id:
            data["project_id"] = project_id
        if due_string:
            data["due_string"] = due_string
        elif due_date:
            data["due_date"] = due_date
        if labels:
            data["labels"] = labels

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create task: {response.text}")

            return response.json()

    async def update_task(
        self,
        access_token: str,
        task_id: str,
        content: Optional[str] = None,
        description: Optional[str] = None,
        due_string: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[int] = None,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Update a task.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID
            content: New task content
            description: New task description
            due_string: Natural language due date
            due_date: Due date in YYYY-MM-DD format
            priority: Priority (1-4)
            labels: List of label names

        Returns:
            Updated task

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {}
        if content is not None:
            data["content"] = content
        if description is not None:
            data["description"] = description
        if due_string is not None:
            data["due_string"] = due_string
        elif due_date is not None:
            data["due_date"] = due_date
        if priority is not None:
            data["priority"] = priority
        if labels is not None:
            data["labels"] = labels

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks/{task_id}",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to update task: {response.text}")

            return response.json()

    async def close_task(self, access_token: str, task_id: str) -> None:
        """Complete/close a task.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks/{task_id}/close",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to close task: {response.text}")

    async def reopen_task(self, access_token: str, task_id: str) -> None:
        """Reopen a completed task.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks/{task_id}/reopen",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to reopen task: {response.text}")

    async def delete_task(self, access_token: str, task_id: str) -> None:
        """Delete a task.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.delete(
                f"{self.BASE_URL}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to delete task: {response.text}")

    # ============================================================================
    # Labels
    # ============================================================================

    async def get_labels(self, access_token: str) -> List[Dict[str, Any]]:
        """Get all labels.

        Args:
            access_token: Valid Todoist access token

        Returns:
            List of labels

        Raises:
            Exception: If API call fails
        """
        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/labels",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get labels: {response.text}")

            return response.json()

    async def create_label(
        self,
        access_token: str,
        name: str,
        color: Optional[str] = None,
        is_favorite: bool = False,
    ) -> Dict[str, Any]:
        """Create a new label.

        Args:
            access_token: Valid Todoist access token
            name: Label name
            color: Label color
            is_favorite: Whether to mark as favorite

        Returns:
            Created label

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {"name": name, "is_favorite": is_favorite}
        if color:
            data["color"] = color

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/labels",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create label: {response.text}")

            return response.json()

    # ============================================================================
    # Comments
    # ============================================================================

    async def get_comments(
        self,
        access_token: str,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get comments for a task or project.

        Args:
            access_token: Valid Todoist access token
            task_id: Task ID
            project_id: Project ID

        Returns:
            List of comments

        Raises:
            Exception: If API call fails
        """
        params = {}
        if task_id:
            params["task_id"] = task_id
        if project_id:
            params["project_id"] = project_id

        async with self._client_session() as client:
            response = await client.get(
                f"{self.BASE_URL}/comments",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get comments: {response.text}")

            return response.json()

    async def create_comment(
        self,
        access_token: str,
        content: str,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a comment on a task or project.

        Args:
            access_token: Valid Todoist access token
            content: Comment content
            task_id: Task ID
            project_id: Project ID

        Returns:
            Created comment

        Raises:
            Exception: If API call fails
        """
        data: Dict[str, Any] = {"content": content}
        if task_id:
            data["task_id"] = task_id
        if project_id:
            data["project_id"] = project_id

        async with self._client_session() as client:
            response = await client.post(
                f"{self.BASE_URL}/comments",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create comment: {response.text}")

            return response.json()


todoist_service = TodoistService()
