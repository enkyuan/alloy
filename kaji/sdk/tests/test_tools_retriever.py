"""Tests for the decoupled ToolRetriever (#8).

The retriever's embedder and cache are pluggable; the default path needs no
Gemini key and no Redis. These tests inject fakes — no infra, no network.
"""

import pytest

from kaji.runtime.context import ToolExecutionContext
from kaji.runtime.tools import registry as registry_module
from kaji.runtime.tools.registry import ToolRegistry, ToolSpec
from kaji.runtime.tools.retriever import (
    InMemoryEmbeddingCache,
    ToolRetriever,
    cosine_similarity,
)


class FakeEmbedder:
    """Maps known texts to fixed vectors; counts calls."""

    def __init__(self, vectors, default=None):
        self._vectors = vectors
        self._default = default if default is not None else [0.0, 0.0]
        self.calls = 0

    async def embed(self, text):
        self.calls += 1
        for key, vec in self._vectors.items():
            if key in text:
                return vec
        return self._default


class NullEmbedder:
    """Always returns no embedding (simulates no key / unavailable backend)."""

    async def embed(self, text):
        return []


@pytest.fixture
def one_tool(monkeypatch: pytest.MonkeyPatch):
    """Register a single tool and clean up the global registry after."""
    spec = ToolSpec(
        name="weather",
        description="Get the weather for a city.",
        parameters={"type": "object", "properties": {}, "required": []},
        risk="read",
    )
    registry = ToolRegistry()
    monkeypatch.setattr(registry_module, "_default_registry", registry)

    @registry.register(spec)
    async def weather(
        _context: ToolExecutionContext, _args: dict[str, object]
    ) -> dict[str, bool]:
        return {"ok": True}

    yield spec


def test_cosine_similarity_basics():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([0, 0], [1, 1]) == 0.0
    assert cosine_similarity([1, 0], [1, 0, 1]) == 0.0


@pytest.mark.asyncio
async def test_in_memory_cache_round_trips():
    cache = InMemoryEmbeddingCache()
    assert await cache.load() == {}
    await cache.save({"a": [1.0, 2.0]})
    assert await cache.load() == {"a": [1.0, 2.0]}


@pytest.mark.asyncio
async def test_retriever_no_embeddings_falls_back_to_all_tools(one_tool):
    # NullEmbedder yields nothing, so the index stays empty and the retriever
    # returns every registered tool rather than blocking tool use.
    retriever = ToolRetriever(embedder=NullEmbedder())
    result = await retriever.get_top_tools("anything")
    assert result == ["weather"]


@pytest.mark.asyncio
async def test_retriever_ranks_by_similarity(one_tool):
    embedder = FakeEmbedder(
        vectors={"Tool: weather": [1.0, 0.0], "sunny": [1.0, 0.0]},
        default=[0.0, 1.0],
    )
    retriever = ToolRetriever(embedder=embedder)

    # Query close to the tool vector -> matched.
    assert await retriever.get_top_tools("sunny", threshold=0.5) == ["weather"]


@pytest.mark.asyncio
async def test_retriever_below_threshold_returns_empty(one_tool):
    embedder = FakeEmbedder(
        vectors={"Tool: weather": [1.0, 0.0]},
        default=[0.0, 1.0],  # orthogonal query -> similarity 0
    )
    retriever = ToolRetriever(embedder=embedder)
    assert await retriever.get_top_tools("unrelated", threshold=0.5) == []


@pytest.mark.asyncio
async def test_retriever_uses_and_populates_cache(one_tool):
    embedder = FakeEmbedder(vectors={"Tool: weather": [1.0, 0.0], "sunny": [1.0, 0.0]})
    cache = InMemoryEmbeddingCache()

    r1 = ToolRetriever(embedder=embedder, cache=cache)
    await r1.initialize()
    calls_after_first = embedder.calls
    assert calls_after_first >= 1  # embedded the tool at least once
    assert await cache.load() == {"weather": [1.0, 0.0]}

    # A second retriever sharing the cache loads vectors instead of recomputing.
    embedder2 = FakeEmbedder(vectors={"sunny": [1.0, 0.0]})
    r2 = ToolRetriever(embedder=embedder2, cache=cache)
    await r2.initialize()
    # No new tool embeddings computed (cache hit); embedder2 untouched at init.
    assert embedder2.calls == 0


@pytest.mark.asyncio
async def test_retriever_evicts_cached_vectors_with_wrong_dimension(one_tool):
    cache = InMemoryEmbeddingCache()
    await cache.save({"weather": [1.0, 0.0, 0.0]})
    embedder = FakeEmbedder(vectors={"Tool: weather": [1.0, 0.0], "sunny": [1.0, 0.0]})
    retriever = ToolRetriever(embedder=embedder, cache=cache)

    # The first lookup rejects the stale vector and safely falls back to all tools.
    assert await retriever.get_top_tools("sunny", threshold=0.5) == ["weather"]
    assert await cache.load() == {}

    # The next lookup rebuilds the missing vector at the current dimension.
    assert await retriever.get_top_tools("sunny", threshold=0.5) == ["weather"]
    assert await cache.load() == {"weather": [1.0, 0.0]}
