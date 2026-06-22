"""Tool discovery endpoints."""

from fastapi import APIRouter, Depends

from agentkit_serve.server.deps import get_current_supabase_user
from agentkit.infra.realtime.redis import RedisKeys, get_redis_client
from agentkit.runtime.tools.registry import ListToolSpecs

router = APIRouter(prefix="/tools", tags=["tools"])


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
            for spec in ListToolSpecs()
        ]
    }


@router.get("/cache/metrics")
async def cache_metrics(_: dict = Depends(get_current_supabase_user)):
    """Return Agent cache metrics."""
    redis = await get_redis_client()
    hit = await redis.get(RedisKeys.AGENT_CACHE_HIT)
    miss = await redis.get(RedisKeys.AGENT_CACHE_MISS)
    return {
        "hit": int(hit or 0),
        "miss": int(miss or 0),
    }


@router.post("/cache/clear")
async def clear_cache(_: dict = Depends(get_current_supabase_user)):
    """Clear Agent cache entries."""
    redis = await get_redis_client()
    deleted = 0
    async for key in redis.scan_iter(f"{RedisKeys.AGENT_CACHE_PREFIX}*"):
        deleted += await redis.delete(key)
    await redis.delete(RedisKeys.AGENT_CACHE_HIT, RedisKeys.AGENT_CACHE_MISS)
    return {"deleted": deleted}
