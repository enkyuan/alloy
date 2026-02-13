"""Todoist integration routes."""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.routers.dependencies import get_current_supabase_user
from app.schemas.integration import OAuthURLResponse
from app.services.todoist import todoist_service

from .integrations_shared import (
    exchange_oauth_code,
    persist_oauth_state,
    require_integration_token,
    upsert_integration,
    validate_and_consume_oauth_state,
)

logger = logging.getLogger(__name__)
router = APIRouter()


todoist_token_dependency = require_integration_token(
    "todoist",
    not_connected_detail="Todoist not connected",
    resolver=todoist_service.get_valid_token,
)


@router.get("/todoist/auth", response_model=OAuthURLResponse)
async def get_todoist_oauth_url(
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
):
    """Get Todoist OAuth authorization URL."""
    try:
        if not settings.TODOIST_CLIENT_ID or not settings.TODOIST_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Todoist OAuth is not configured",
            )

        state = secrets.token_urlsafe(32)
        await persist_oauth_state(
            state=state, user_id=str(supabase_user["id"]), service="todoist"
        )

        scopes = ["data:read_write", "data:delete", "project:delete"]
        params = {
            "client_id": settings.TODOIST_CLIENT_ID,
            "scope": ",".join(scopes),
            "state": state,
        }
        auth_url = f"https://todoist.com/oauth/authorize?{urlencode(params)}"

        logger.info("Generated Todoist OAuth URL for user %s", supabase_user["id"])
        return OAuthURLResponse(authUrl=auth_url, state=state)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate Todoist OAuth URL: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate OAuth URL",
        )


@router.get("/todoist/callback")
async def todoist_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Todoist OAuth callback and redirect to iOS app."""
    redirect_url = f"havenos://todoist/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/todoist/exchange")
async def todoist_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    supabase_user: dict[str, Any] = Depends(get_current_supabase_user),
    db: AsyncSession = Depends(get_db),
):
    """Exchange Todoist authorization code for access token."""
    try:
        user_id = str(supabase_user["id"])
        await validate_and_consume_oauth_state(state=state, user_id=user_id)

        token_data = await exchange_oauth_code(
            token_url="https://todoist.com/oauth/access_token",
            form_data={
                "client_id": settings.TODOIST_CLIENT_ID,
                "client_secret": settings.TODOIST_CLIENT_SECRET,
                "code": code,
            },
        )

        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)
        await upsert_integration(
            db=db,
            user_id=user_id,
            service="todoist",
            access_token=token_data["access_token"],
            token_type="Bearer",
            expires_at=expires_at,
        )

        logger.info("Successfully connected Todoist for user %s", user_id)
        return {
            "success": True,
            "message": "Successfully connected Todoist",
            "service": "todoist",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Todoist code exchange failed: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to exchange code",
        )


# ============================================================================
# Todoist API Endpoints
# ============================================================================


@router.get("/todoist/tasks")
async def get_todoist_tasks(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    label: Optional[str] = Query(None, description="Filter by label"),
    filter_query: Optional[str] = Query(None, description="Todoist filter query"),
    todoist_token: str = Depends(todoist_token_dependency),
):
    """Get Todoist tasks."""
    try:
        tasks = await todoist_service.get_tasks(
            todoist_token, project_id=project_id, label=label, filter_query=filter_query
        )
        return {"tasks": tasks}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Todoist tasks: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get tasks",
        )


@router.post("/todoist/tasks")
async def create_todoist_task(
    content: str = Query(..., description="Task content"),
    description: Optional[str] = Query(None, description="Task description"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    due_string: Optional[str] = Query(None, description="Natural language due date"),
    priority: int = Query(1, ge=1, le=4, description="Priority (1-4)"),
    todoist_token: str = Depends(todoist_token_dependency),
):
    """Create a Todoist task."""
    try:
        task = await todoist_service.create_task(
            todoist_token,
            content=content,
            description=description,
            project_id=project_id,
            due_string=due_string,
            priority=priority,
        )
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create Todoist task: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create task",
        )


@router.post("/todoist/tasks/{task_id}/close")
async def close_todoist_task(
    task_id: str,
    todoist_token: str = Depends(todoist_token_dependency),
):
    """Complete a Todoist task."""
    try:
        await todoist_service.close_task(todoist_token, task_id)
        return {"success": True, "message": "Task completed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to close Todoist task: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to close task",
        )


@router.get("/todoist/projects")
async def get_todoist_projects(
    todoist_token: str = Depends(todoist_token_dependency),
):
    """Get Todoist projects."""
    try:
        projects = await todoist_service.get_projects(todoist_token)
        return {"projects": projects}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Todoist projects: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get projects",
        )
