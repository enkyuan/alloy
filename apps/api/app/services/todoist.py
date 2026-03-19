"""Todoist API service."""

from __future__ import annotations

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

    async def get_project(self, access_token: str, project_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/projects/{project_id}",
            action="get project",
            headers=self._auth_headers(access_token),
        )

    async def create_project(
        self,
        access_token: str,
        name: str,
        color: str | None = None,
        parent_id: str | None = None,
        is_favorite: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name, "is_favorite": is_favorite}
        if color:
            data["color"] = color
        if parent_id:
            data["parent_id"] = parent_id
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/projects",
            action="create project",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )

    async def update_project(
        self,
        access_token: str,
        project_id: str,
        name: str | None = None,
        color: str | None = None,
        is_favorite: bool | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if color is not None:
            data["color"] = color
        if is_favorite is not None:
            data["is_favorite"] = is_favorite
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

    async def get_tasks(
        self,
        access_token: str,
        project_id: str | None = None,
        label: str | None = None,
        filter_query: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
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

    async def get_task(self, access_token: str, task_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/tasks/{task_id}",
            action="get task",
            headers=self._auth_headers(access_token),
        )

    async def create_task(
        self,
        access_token: str,
        content: str,
        description: str | None = None,
        project_id: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int = 1,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"content": content, "priority": priority}
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
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/tasks",
            action="create task",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )

    async def update_task(
        self,
        access_token: str,
        task_id: str,
        content: str | None = None,
        description: str | None = None,
        due_string: str | None = None,
        due_date: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
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

    async def delete_task(self, access_token: str, task_id: str) -> None:
        await self._request_no_content(
            "DELETE",
            f"{self.BASE_URL}/tasks/{task_id}",
            action="delete task",
            headers=self._auth_headers(access_token),
            expected_status=(200, 204),
        )

    async def get_labels(self, access_token: str) -> list[dict[str, Any]]:
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/labels",
            action="get labels",
            headers=self._auth_headers(access_token),
        )

    async def create_label(
        self,
        access_token: str,
        name: str,
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

    async def get_comments(
        self,
        access_token: str,
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if task_id:
            params["task_id"] = task_id
        if project_id:
            params["project_id"] = project_id
        return await self._request_json(
            "GET",
            f"{self.BASE_URL}/comments",
            action="get comments",
            headers=self._auth_headers(access_token),
            params=params,
        )

    async def create_comment(
        self,
        access_token: str,
        content: str,
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"content": content}
        if task_id:
            data["task_id"] = task_id
        if project_id:
            data["project_id"] = project_id
        return await self._request_json(
            "POST",
            f"{self.BASE_URL}/comments",
            action="create comment",
            headers=self._auth_headers(access_token),
            json=data,
            expected_status=(200, 201),
        )


todoist_service = TodoistService()
