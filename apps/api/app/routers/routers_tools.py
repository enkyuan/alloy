"""Tool discovery endpoints."""

from fastapi import APIRouter

import app.services.integrations.tools  # ensure tool registration
from app.core.redis import get_redis_client
from app.services.integrations import list_tool_specs

router = APIRouter(prefix="/tools", tags=["tools"])

CACHE_KEY_PREFIX = "agent:cache:"
HIT_KEY = "agent:cache:hit"
MISS_KEY = "agent:cache:miss"


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
async def cache_metrics():
    """Return Agent cache metrics."""
    redis = await get_redis_client()
    hit = await redis.get(HIT_KEY)
    miss = await redis.get(MISS_KEY)
    return {
        "hit": int(hit or 0),
        "miss": int(miss or 0),
    }


@router.post("/cache/clear")
async def clear_cache():
    """Clear Agent cache entries."""
    redis = await get_redis_client()
    deleted = 0
    async for key in redis.scan_iter(f"{CACHE_KEY_PREFIX}*"):
        deleted += await redis.delete(key)
    await redis.delete(HIT_KEY, MISS_KEY)
    return {"deleted": deleted}
