"""Todoist API service."""

<<<<<<< HEAD
=======
from __future__ import annotations

>>>>>>> codex/refactor
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.integration import Integration
from app.services.integrations.base import IntegrationHTTPService

logger = logging.getLogger(__name__)


class TodoistService(IntegrationHTTPService):
    """Service for Todoist API operations."""

    SERVICE_NAME = "todoist"
    BASE_URL = settings.TODOIST_API_BASE_URL
    TOKEN_VALIDITY_EXTENSION_DAYS = 365 * 10
    TOKEN_REFRESH_WINDOW_DAYS = 30

    async def refresh_token(self, integration: Integration, db: AsyncSession) -> str:
        # Todoist tokens are effectively non-expiring.
        now = datetime.now(timezone.utc)
        integration.expires_at = now + timedelta(days=self.TOKEN_VALIDITY_EXTENSION_DAYS)
        integration.updated_at = now
        await self._commit(db)
        logger.info(
            "Extended Todoist token validity",
            extra={"user_id": str(integration.user_id)},
        )
        return str(integration.access_token)

<<<<<<< HEAD
        Args:
            integration: Integration model with refresh token
            db: Database session

        Returns:
            New access token

        Raises:
            Exception: If token refresh fails
        """
        try:
            if not integration.refresh_token:
                raise Exception("No refresh token available")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://todoist.com/oauth/access_token",
                    data={
                        "client_id": settings.TODOIST_CLIENT_ID,
                        "client_secret": settings.TODOIST_CLIENT_SECRET,
                        "refresh_token": integration.refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
=======
    async def get_valid_token(self, integration: Integration, db: AsyncSession) -> str:
        expires_at = integration.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc) + timedelta(
                days=self.TOKEN_REFRESH_WINDOW_DAYS
            ):
                logger.info(
                    "Todoist token expiring soon, extending validity",
                    extra={"user_id": str(integration.user_id)},
>>>>>>> codex/refactor
                )
                return await self.refresh_token(integration, db)
        return str(integration.access_token)

    async def get_projects(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/projects",
            action="get projects",
            headers=self._auth_headers(access_token),
        )

<<<<<<< HEAD
                token_data = response.json()

                # Update integration
                integration.access_token = token_data["access_token"]
                # Todoist tokens don't expire, but we'll set a far future date
                integration.expires_at = datetime.utcnow() + timedelta(days=365 * 10)
                integration.updated_at = datetime.utcnow()

                db.commit()

                logger.info(
                    f"Successfully refreshed Todoist token for user {integration.user_id}"
                )
                return integration.access_token

        except Exception as e:
            logger.error(f"Failed to refresh Todoist token: {str(e)}", exc_info=True)
            raise

    async def get_valid_token(self, integration: Integration, db: Session) -> str:
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
            and integration.expires_at < datetime.utcnow() + timedelta(days=30)
        ):
            logger.info("Todoist token expiring soon, refreshing...")
            return await self.refresh_token(integration, db)

        return integration.access_token

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
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/projects/{project_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get project: {response.text}")

            return response.json()
=======
    async def get_project(self, access_token: str, project_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/projects/{project_id}",
            action="get project",
            headers=self._auth_headers(access_token),
        )
>>>>>>> codex/refactor

    async def create_project(
        self,
        access_token: str,
        name: str,
<<<<<<< HEAD
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
        data = {"name": name, "is_favorite": is_favorite}
=======
        color: str | None = None,
        parent_id: str | None = None,
        is_favorite: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name, "is_favorite": is_favorite}
>>>>>>> codex/refactor
        if color:
            data["color"] = color
        if parent_id:
            data["parent_id"] = parent_id
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/projects",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create project: {response.text}")

            return response.json()
=======
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/projects",
            action="create project",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )
>>>>>>> codex/refactor

    async def update_project(
        self,
        access_token: str,
        project_id: str,
<<<<<<< HEAD
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
        data = {}
=======
        name: str | None = None,
        color: str | None = None,
        is_favorite: bool | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
>>>>>>> codex/refactor
        if name is not None:
            data["name"] = name
        if color is not None:
            data["color"] = color
        if is_favorite is not None:
            data["is_favorite"] = is_favorite
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.BASE_URL}/projects/{project_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to delete project: {response.text}")

    # ============================================================================
    # Tasks
    # ============================================================================
=======
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/projects/{project_id}",
            action="update project",
            headers=self._auth_headers(access_token),
            json=data,
        )

    async def delete_project(self, access_token: str, project_id: str) -> None:
        await self._request_no_content(
            "DELETE",
            f"{self.BASE_URL}/projects/{project_id}",
            action="delete project",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )
>>>>>>> codex/refactor

    async def get_tasks(
        self,
        access_token: str,
<<<<<<< HEAD
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
=======
        project_id: str | None = None,
        label: str | None = None,
        filter_query: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
>>>>>>> codex/refactor
        if project_id:
            params["project_id"] = project_id
        if label:
            params["label"] = label
        if filter_query:
            params["filter"] = filter_query
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/tasks",
            action="get tasks",
            headers=self._auth_headers(access_token),
            params=params,
        )

<<<<<<< HEAD
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/tasks/{task_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get task: {response.text}")

            return response.json()
=======
    async def get_task(self, access_token: str, task_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/tasks/{task_id}",
            action="get task",
            headers=self._auth_headers(access_token),
        )
>>>>>>> codex/refactor

    async def create_task(
        self,
        access_token: str,
        content: str,
        description: str | None = None,
        project_id: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int = 1,
<<<<<<< HEAD
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
        data = {"content": content, "priority": priority}
=======
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"content": content, "priority": priority}
>>>>>>> codex/refactor
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
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create task: {response.text}")

            return response.json()
=======
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/tasks",
            action="create task",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )
>>>>>>> codex/refactor

    async def update_task(
        self,
        access_token: str,
        task_id: str,
<<<<<<< HEAD
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
        data = {}
=======
        content: str | None = None,
        description: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
>>>>>>> codex/refactor
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
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/tasks/{task_id}/reopen",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 204]:
                raise Exception(f"Failed to reopen task: {response.text}")
=======
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/tasks/{task_id}",
            action="update task",
            headers=self._auth_headers(access_token),
            json=data,
        )

    async def close_task(self, access_token: str, task_id: str) -> None:
        await self._request_no_content(
            "POST",
            f"{self.BASE_URL}/tasks/{task_id}/close",
            action="close task",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def reopen_task(self, access_token: str, task_id: str) -> None:
        await self._request_no_content(
            "POST",
            f"{self.BASE_URL}/tasks/{task_id}/reopen",
            action="reopen task",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )
>>>>>>> codex/refactor

    async def delete_task(self, access_token: str, task_id: str) -> None:
        await self._request_no_content(
            "DELETE",
            f"{self.BASE_URL}/tasks/{task_id}",
            action="delete task",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

<<<<<<< HEAD
        Args:
            access_token: Valid Todoist access token
            task_id: Task ID

        Raises:
            Exception: If API call fails
        """
        async with httpx.AsyncClient() as client:
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
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/labels",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get labels: {response.text}")

            return response.json()
=======
    async def get_labels(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/labels",
            action="get labels",
            headers=self._auth_headers(access_token),
        )
>>>>>>> codex/refactor

    async def create_label(
        self,
        access_token: str,
        name: str,
<<<<<<< HEAD
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
        data = {"name": name, "is_favorite": is_favorite}
        if color:
            data["color"] = color

        async with httpx.AsyncClient() as client:
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
=======
        color: str | None = None,
        is_favorite: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name, "is_favorite": is_favorite}
        if color:
            data["color"] = color
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/labels",
            action="create label",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )
>>>>>>> codex/refactor

    async def get_comments(
        self,
        access_token: str,
<<<<<<< HEAD
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
=======
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
>>>>>>> codex/refactor
        if task_id:
            params["task_id"] = task_id
        if project_id:
            params["project_id"] = project_id
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/comments",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code != 200:
                raise Exception(f"Failed to get comments: {response.text}")

            return response.json()
=======
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/comments",
            action="get comments",
            headers=self._auth_headers(access_token),
            params=params,
        )
>>>>>>> codex/refactor

    async def create_comment(
        self,
        access_token: str,
        content: str,
<<<<<<< HEAD
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
        data = {"content": content}
=======
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"content": content}
>>>>>>> codex/refactor
        if task_id:
            data["task_id"] = task_id
        if project_id:
            data["project_id"] = project_id
<<<<<<< HEAD

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/comments",
                json=data,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Failed to create comment: {response.text}")

            return response.json()
=======
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/comments",
            action="create comment",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )
>>>>>>> codex/refactor


todoist_service = TodoistService()
