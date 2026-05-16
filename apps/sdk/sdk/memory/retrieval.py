"""Memory retrieval — in-memory implementation for development and tests."""

from __future__ import annotations

from sdk.memory.schemas import MemoryQuery, MemoryRecord


class InMemoryMemoryRetriever:
    """Simple substring retriever backed by an in-process list."""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    def add(self, record: MemoryRecord) -> None:
        self._records.append(record)

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        needle = query.query.lower().strip()
        matches = [
            record
            for record in self._records
            if (query.session_id is None or record.session_id == query.session_id)
            and needle in record.content.lower()
        ]
        matches.sort(key=lambda record: record.score, reverse=True)
        return matches[: query.top_k]
