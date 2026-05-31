"""In-process metrics counters for development and tests."""

from __future__ import annotations

from collections import defaultdict

from agentkit.core.redis import RedisKeys

__all__ = ["InMemoryMetrics", "RedisKeys"]


class InMemoryMetrics:
    """Thread-unsafe counter registry suitable for unit tests."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    def increment(self, name: str, amount: int = 1) -> None:
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self._counters[name] += amount

    def get(self, name: str) -> int:
        return self._counters[name]

    def reset(self) -> None:
        self._counters.clear()
