import logging

import pytest

from agentkit.knowledge.rag import DocumentRAG
from agentkit.knowledge.store import InMemoryVectorStore
from agentkit.knowledge.types import Document


class StubEmbedder:
    """Deterministic 2-D embedder: maps a keyword to an axis. No network."""

    async def embed(self, text: str) -> list[float]:
        t = text.lower()
        cat = 1.0 if "cat" in t else 0.0
        dog = 1.0 if "dog" in t else 0.0
        if cat == 0.0 and dog == 0.0:
            return []  # mimic the "no embedding" path
        return [cat, dog]


@pytest.mark.asyncio
async def test_add_document_chunks_and_embeds():
    rag = DocumentRAG(embedder=StubEmbedder(), store=InMemoryVectorStore())
    n = await rag.add_document(
        Document(id="d1", text="cats are great. " * 50), chunk_size=40, overlap=10
    )
    assert n > 1  # long doc produced multiple chunks


@pytest.mark.asyncio
async def test_retrieve_returns_relevant_chunk():
    rag = DocumentRAG(embedder=StubEmbedder(), store=InMemoryVectorStore())
    await rag.add_document(Document(id="c", text="cats purr"))
    await rag.add_document(Document(id="d", text="dogs bark"))
    results = await rag.retrieve("tell me about cats", top_k=1, threshold=0.1)
    assert len(results) == 1
    assert "cat" in results[0].text.lower()


@pytest.mark.asyncio
async def test_retrieve_with_unembeddable_query_returns_empty():
    rag = DocumentRAG(embedder=StubEmbedder(), store=InMemoryVectorStore())
    await rag.add_document(Document(id="c", text="cats purr"))
    # query has no cat/dog keyword -> stub returns [] -> no retrieval
    assert await rag.retrieve("hello", top_k=5, threshold=0.1) == []


@pytest.mark.asyncio
async def test_rag_is_infra_free_by_default():
    # Constructing with no args must not touch network/env.
    rag = DocumentRAG()
    # With no embedder key configured, GeminiEmbedder returns [] -> add stores nothing.
    n = await rag.add_document(Document(id="d", text="anything"))
    assert n == 0
    assert await rag.retrieve("anything") == []


@pytest.mark.asyncio
async def test_add_document_warns_when_nothing_embedded(caplog):
    # F3: 0 chunks from non-empty text should produce an actionable warning.
    rag = DocumentRAG()  # default embedder returns [] with no key
    with caplog.at_level(logging.WARNING):
        n = await rag.add_document(Document(id="d", text="non-empty text here"))
    assert n == 0
    assert any("stored 0" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_add_empty_document_does_not_warn(caplog):
    # Empty text legitimately yields 0 chunks; no warning noise.
    rag = DocumentRAG(embedder=StubEmbedder(), store=InMemoryVectorStore())
    with caplog.at_level(logging.WARNING):
        n = await rag.add_document(Document(id="d", text="   "))
    assert n == 0
    assert not any("stored 0" in r.message for r in caplog.records)


class ExplodingEmbedder:
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedder down")


@pytest.mark.asyncio
async def test_embedder_failure_does_not_crash_ingestion():
    rag = DocumentRAG(embedder=ExplodingEmbedder(), store=InMemoryVectorStore())
    n = await rag.add_document(Document(id="d", text="some text"))
    assert n == 0  # failure swallowed per-chunk, ingestion returns 0
