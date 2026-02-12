"""Tool discovery endpoints."""

from typing import Any

from fastapi import APIRouter, Header, HTTPException, status

import app.services.integrations.tools  # ensure tool registration
from app.core.redis import get_redis_client
from app.services.integrations import list_tool_specs
from app.services.user.auth import supabase_auth_service

router = APIRouter(prefix="/tools", tags=["tools"])

CACHE_KEY_PREFIX = "agent:cache:"
HIT_KEY = "agent:cache:hit"
MISS_KEY = "agent:cache:miss"


async def _require_authenticated_user(authorization: str | None) -> dict[str, Any]:
    """Validate a Bearer token and return the resolved Supabase user."""
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
    return supabase_user


@router.get("")
async def list_tools():
    """List available Agent tool definitions."""
    return {
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in list_tool_specs()
        ]
    }


@router.get("/cache/metrics")
async def cache_metrics(authorization: str = Header(None)):
    """Return Agent cache metrics."""
    await _require_authenticated_user(authorization)
    redis = await get_redis_client()
    hit = await redis.get(HIT_KEY)
    miss = await redis.get(MISS_KEY)
    return {
        "hit": int(hit or 0),
        "miss": int(miss or 0),
    }


@router.post("/cache/clear")
async def clear_cache(authorization: str = Header(None)):
    """Clear Agent cache entries."""
    await _require_authenticated_user(authorization)
    redis = await get_redis_client()
    deleted = 0
    async for key in redis.scan_iter(f"{CACHE_KEY_PREFIX}*"):
        deleted += await redis.delete(key)
    await redis.delete(HIT_KEY, MISS_KEY)
    return {"deleted": deleted}
