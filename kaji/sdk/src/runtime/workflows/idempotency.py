"""Workflow idempotency keys and deduplication store."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_idempotency_key(*, workflow: str, payload: dict[str, Any]) -> str:
    """Derive a stable idempotency key from workflow name and payload."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{workflow}:{body}".encode("utf-8")).hexdigest()
    return digest[:32]


class IdempotencyStore:
    """In-memory deduplication guard for workflow side effects."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, key: str) -> bool:
        """Return True when the key is newly claimed, False if already seen."""
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True

    def release(self, key: str) -> None:
        self._claimed.discard(key)
