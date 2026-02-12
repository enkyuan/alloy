"""Todoist integration routes."""

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.integration import Integration
from app.schemas.integration import OAuthURLResponse
from app.services.user.auth import supabase_auth_service

from .integrations_shared import OAUTH_STATE_TTL, redis_client

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# Todoist Integration Routes
# ============================================================================


@router.get("/todoist/auth", response_model=OAuthURLResponse)
async def get_todoist_oauth_url(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Todoist OAuth authorization URL.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        OAuthURLResponse with authorization URL and state

    Raises:
        HTTPException: If authentication fails or Todoist is not configured
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("Missing or invalid authorization header")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            logger.warning("Invalid or expired token provided")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Check if Todoist is configured
        if not settings.TODOIST_CLIENT_ID or not settings.TODOIST_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Todoist OAuth is not configured",
            )

        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(32)

        # Store state with user ID in Redis with TTL
        state_data = {
            "user_id": supabase_user["id"],
            "service": "todoist",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await redis_client.setex(
            f"oauth_state:{state}", OAUTH_STATE_TTL, json.dumps(state_data)
        )

        # Build Todoist OAuth URL
        scopes = ["data:read_write", "data:delete", "project:delete"]

        params = {
            "client_id": settings.TODOIST_CLIENT_ID,
            "scope": ",".join(scopes),
            "state": state,
        }

        auth_url = f"https://todoist.com/oauth/authorize?{urlencode(params)}"

        logger.info(f"Generated Todoist OAuth URL for user {supabase_user['id']}")

        return OAuthURLResponse(authUrl=auth_url, state=state)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate Todoist OAuth URL: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate OAuth URL: {str(e)}",
        )


@router.get("/todoist/callback")
async def todoist_oauth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
):
    """Handle Todoist OAuth callback and redirect to iOS app.

    This endpoint receives the OAuth callback from Todoist and redirects
    to the iOS app with the code and state parameters.

    Args:
        code: Authorization code from Todoist
        state: State parameter for CSRF protection

    Returns:
        Redirect to iOS app with code and state
    """
    # Redirect to iOS app with code and state
    redirect_url = f"havenos://todoist/callback?code={code}&state={state}"
    return RedirectResponse(url=redirect_url)


@router.post("/todoist/exchange")
async def todoist_exchange_code(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state parameter"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Exchange Todoist authorization code for access token.

    This endpoint is called by the iOS app after receiving the callback.

    Args:
        code: Authorization code from Todoist
        state: State parameter for CSRF protection
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success response with integration status

    Raises:
        HTTPException: If exchange fails
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")

        # Verify token and get user from Supabase
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Validate state parameter from Redis
        state_key = f"oauth_state:{state}"
        state_json = await redis_client.get(state_key)

        if not state_json:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter",
            )

        # Verify state belongs to this user
        state_data = json.loads(state_json)
        if state_data["user_id"] != supabase_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="State parameter does not match user",
            )

        # Delete state from Redis (one-time use)
        await redis_client.delete(state_key)

        user_id = supabase_user["id"]

        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://todoist.com/oauth/access_token",
                data={
                    "client_id": settings.TODOIST_CLIENT_ID,
                    "client_secret": settings.TODOIST_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if token_response.status_code != 200:
            logger.error(f"Todoist token exchange failed: {token_response.text}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange authorization code",
            )

        token_data = token_response.json()

        # Todoist tokens don't expire, set far future date
        expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)

        # Check if integration already exists
        existing_integration = (
            db.query(Integration)
            .filter(Integration.user_id == user_id, Integration.service == "todoist")
            .first()
        )

        if existing_integration:
            # Update existing integration
            existing_integration.access_token = token_data["access_token"]
            existing_integration.token_type = "Bearer"
            existing_integration.expires_at = expires_at
            existing_integration.is_active = True
            existing_integration.updated_at = datetime.now(timezone.utc)
        else:
            # Create new integration
            integration = Integration(
                id=str(uuid.uuid4()),
                user_id=user_id,
                service="todoist",
                access_token=token_data["access_token"],
                token_type="Bearer",
                expires_at=expires_at,
                is_active=True,
            )
            db.add(integration)

        db.commit()

        logger.info(f"Successfully connected Todoist for user {user_id}")

        return {
            "success": True,
            "message": "Successfully connected Todoist",
            "service": "todoist",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Todoist code exchange failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exchange code: {str(e)}",
        )


# ============================================================================
# Todoist API Endpoints
# ============================================================================


@router.get("/todoist/tasks")
async def get_todoist_tasks(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    label: Optional[str] = Query(None, description="Filter by label"),
    filter_query: Optional[str] = Query(None, description="Todoist filter query"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Get Todoist tasks.

    Args:
        project_id: Filter by project ID
        label: Filter by label
        filter_query: Todoist filter query
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of tasks

    Raises:
        HTTPException: If not authenticated or Todoist not connected
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Get tasks
        tasks = await todoist_service.get_tasks(
            todoist_token, project_id=project_id, label=label, filter_query=filter_query
        )

        return {"tasks": tasks}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Todoist tasks: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tasks: {str(e)}",
        )


@router.post("/todoist/tasks")
async def create_todoist_task(
    content: str = Query(..., description="Task content"),
    description: Optional[str] = Query(None, description="Task description"),
    project_id: Optional[str] = Query(None, description="Project ID"),
    due_string: Optional[str] = Query(None, description="Natural language due date"),
    priority: int = Query(1, ge=1, le=4, description="Priority (1-4)"),
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Create a Todoist task.

    Args:
        content: Task content/title
        description: Task description
        project_id: Project ID
        due_string: Natural language due date
        priority: Priority (1-4)
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Created task

    Raises:
        HTTPException: If not authenticated or Todoist not connected
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Create task
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
        logger.error(f"Failed to create Todoist task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}",
        )


@router.post("/todoist/tasks/{task_id}/close")
async def close_todoist_task(
    task_id: str, authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Complete a Todoist task.

    Args:
        task_id: Task ID
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If not authenticated or Todoist not connected
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Close task
        await todoist_service.close_task(todoist_token, task_id)

        return {"success": True, "message": "Task completed"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close Todoist task: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to close task: {str(e)}",
        )


@router.get("/todoist/projects")
async def get_todoist_projects(
    authorization: str = Header(None), db: Session = Depends(get_db)
):
    """Get Todoist projects.

    Args:
        authorization: Bearer token from Authorization header
        db: Database session

    Returns:
        List of projects

    Raises:
        HTTPException: If not authenticated or Todoist not connected
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        access_token = authorization.replace("Bearer ", "")
        supabase_user = await supabase_auth_service.get_user(access_token)

        if not supabase_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Get Todoist integration
        integration = (
            db.query(Integration)
            .filter(
                Integration.user_id == supabase_user["id"],
                Integration.service == "todoist",
                Integration.is_active == True,
            )
            .first()
        )

        if not integration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Todoist not connected"
            )

        # Import todoist service
        from app.services.todoist import todoist_service

        # Get valid token
        todoist_token = await todoist_service.get_valid_token(integration, db)

        # Get projects
        projects = await todoist_service.get_projects(todoist_token)

        return {"projects": projects}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Todoist projects: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get projects: {str(e)}",
        )

