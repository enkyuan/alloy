import pytest

from sdk.memory import (
    InMemoryMemoryRetriever,
    MemoryQuery,
    MemoryRecord,
    WorkingMemory,
    rerank_by_score,
)


def test_working_memory_evicts_oldest_when_full():
    memory = WorkingMemory(max_messages=2)
    memory.append("user", "one")
    memory.append("assistant", "two")
    memory.append("user", "three")

    snapshot = memory.snapshot()
    assert len(snapshot) == 2
    assert snapshot[0]["content"] == "two"
    assert snapshot[1]["content"] == "three"


def test_working_memory_clear():
    memory = WorkingMemory()
    memory.append("user", "hi")
    memory.clear()
    assert memory.snapshot() == []


def test_memory_retriever_filters_by_session_and_query():
    retriever = InMemoryMemoryRetriever()
    retriever.add(
        MemoryRecord(
            id="1",
            session_id="s1",
            content="schedule a meeting tomorrow",
            score=0.5,
        )
    )
    retriever.add(
        MemoryRecord(
            id="2",
            session_id="s2",
            content="schedule lunch",
            score=0.9,
        )
    )

    results = retriever.search(
        MemoryQuery(query="schedule", session_id="s1", top_k=5)
    )
    assert len(results) == 1
    assert results[0].id == "1"


def test_rerank_by_score_orders_descending():
    records = [
        MemoryRecord(id="a", session_id="s", content="a", score=0.1),
        MemoryRecord(id="b", session_id="s", content="b", score=0.9),
        MemoryRecord(id="c", session_id="s", content="c", score=0.5),
    ]
    ranked = rerank_by_score(records, limit=2)
    assert [record.id for record in ranked] == ["b", "c"]


def test_rerank_by_score_rejects_invalid_limit():
    with pytest.raises(ValueError, match="limit must be at least 1"):
        rerank_by_score([], limit=0)
