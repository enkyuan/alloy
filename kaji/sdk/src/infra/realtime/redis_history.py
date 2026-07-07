"""Redis-backed conversation history store for reasoning nodes (opt-in).

Satisfies the ``HistoryStore`` protocol by adapting the existing
``redis_events`` history helpers. Lives in the realtime/Redis layer so importing
a reasoning node pulls in no Redis dependency — the default history store is
in-memory. Wire this in for durable, cross-process history::

    from kaji.infra.realtime.redis_history import RedisHistoryStore
    node = AgentReasoningNode(system_prompt=..., history_store=RedisHistoryStore())
"""

from typing import Any, Dict, List, Optional

from kaji.infra.realtime.redis import get_redis_client
from kaji.infra.realtime.history_ops import append_history, get_history


class RedisHistoryStore:
    """Durable conversation history backed by Redis lists.

    Resolves the shared Redis client lazily on first use (so construction needs
    no live connection). Pass an explicit client to override.
    """

    def __init__(self, redis: Optional[Any] = None) -> None:
        self._redis = redis

    async def _client(self) -> Any:
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis

    async def append(
        self, key: str, role: str, content: str, *, history_limit: int
    ) -> None:
        redis = await self._client()
        await append_history(redis, key, role, content, history_limit=history_limit)

    async def get(self, key: str) -> List[Dict[str, str]]:
        redis = await self._client()
        return await get_history(redis, key)
