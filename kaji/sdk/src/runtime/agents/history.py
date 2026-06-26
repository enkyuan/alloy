"""Conversation history backends for reasoning nodes.

A ``HistoryStore`` is how a reasoning node persists and reads back the running
conversation. The default ``InMemoryHistoryStore`` keeps history in-process (no
infra), so a node runs embedded with no Redis. The reference service injects a
Redis-backed store (``RedisHistoryStore``) for cross-process, durable history.
"""

from collections import defaultdict
from typing import Dict, List, Protocol


class HistoryStore(Protocol):
    """Append-and-read conversation history, keyed by conversation id."""

    async def append(
        self, key: str, role: str, content: str, *, history_limit: int
    ) -> None: ...

    async def get(self, key: str) -> List[Dict[str, str]]: ...


class InMemoryHistoryStore:
    """Process-local history — no infra. Lost on restart.

    Matches the Redis store's semantics: skips exact consecutive duplicates and
    trims to the most recent ``history_limit`` entries.
    """

    def __init__(self) -> None:
        self._store: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    async def append(
        self, key: str, role: str, content: str, *, history_limit: int
    ) -> None:
        entries = self._store[key]
        entry = {"role": role, "content": content}

        if entries and entries[-1] == entry:
            return  # skip exact consecutive duplicate

        entries.append(entry)
        if history_limit > 0 and len(entries) > history_limit:
            del entries[:-history_limit]

    async def get(self, key: str) -> List[Dict[str, str]]:
        return [dict(entry) for entry in self._store[key]]
