import pytest

from kaji.knowledge.store import InMemoryVectorStore
from kaji.knowledge.types import Chunk


def _chunk(doc_id: str, text: str, idx: int, vec: list[float]) -> Chunk:
    return Chunk(document_id=doc_id, text=text, index=idx, embedding=vec)


@pytest.mark.asyncio
async def test_add_and_search_returns_nearest():
    store = InMemoryVectorStore()
    await store.add(
        [
            _chunk("d1", "cats", 0, [1.0, 0.0]),
            _chunk("d1", "dogs", 1, [0.0, 1.0]),
        ]
    )
    results = await store.search([0.9, 0.1], top_k=1, threshold=0.0)
    assert len(results) == 1
    assert results[0].text == "cats"


@pytest.mark.asyncio
async def test_threshold_filters_low_similarity():
    store = InMemoryVectorStore()
    await store.add([_chunk("d1", "cats", 0, [1.0, 0.0])])
    # query orthogonal to the only chunk -> similarity 0, below threshold
    results = await store.search([0.0, 1.0], top_k=5, threshold=0.5)
    assert results == []


@pytest.mark.asyncio
async def test_top_k_limits_results():
    store = InMemoryVectorStore()
    await store.add(
        [
            _chunk("d", "a", 0, [1.0, 0.0]),
            _chunk("d", "b", 1, [0.9, 0.1]),
            _chunk("d", "c", 2, [0.8, 0.2]),
        ]
    )
    results = await store.search([1.0, 0.0], top_k=2, threshold=0.0)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_empty_store_returns_empty():
    store = InMemoryVectorStore()
    assert await store.search([1.0, 0.0], top_k=5, threshold=0.0) == []


@pytest.mark.asyncio
async def test_chunks_without_embeddings_are_skipped():
    store = InMemoryVectorStore()
    await store.add([_chunk("d", "no-vec", 0, [])])
    assert await store.search([1.0, 0.0], top_k=5, threshold=0.0) == []


@pytest.mark.asyncio
async def test_mismatched_dimension_chunk_is_skipped_not_truncated():
    # H4: a 3-d chunk must never be cosine-compared (via zip truncation) to a
    # 2-d query. It is skipped, so only the 2-d chunk can match.
    store = InMemoryVectorStore()
    await store.add(
        [
            _chunk("d", "two-d", 0, [1.0, 0.0]),
            _chunk("d", "three-d", 1, [1.0, 0.0, 5.0]),
        ]
    )
    results = await store.search([1.0, 0.0], top_k=5, threshold=0.0)
    assert [c.text for c in results] == ["two-d"]
