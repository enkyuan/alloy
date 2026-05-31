"""Memory reranking helpers."""

from __future__ import annotations

from agentkit.memory.schemas import MemoryRecord


def rerank_by_score(records: list[MemoryRecord], *, limit: int = 5) -> list[MemoryRecord]:
    """Return the highest-scoring records up to ``limit``."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    ordered = sorted(records, key=lambda record: record.score, reverse=True)
    return ordered[:limit]
