"""Memory record schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    """A single retrievable memory document."""

    id: str
    session_id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0


class MemoryQuery(BaseModel):
    """Query parameters for memory retrieval."""

    query: str
    top_k: int = Field(default=5, ge=1, le=100)
    session_id: str | None = None
