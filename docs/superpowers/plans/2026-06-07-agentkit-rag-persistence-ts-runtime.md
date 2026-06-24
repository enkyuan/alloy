<!-- /autoplan restore point: /Users/Enkang.Yuan1/.gstack/projects/enkyuan-alloy/feat-kaji-rag-persistence-ts-runtime-autoplan-restore-20260607-132529.md -->
# Kaji: Document RAG + Durable Persistence + TS Runtime Parity

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four roadmap gaps across the two Kaji SDKs without breaking the infra-free guarantee (`import kaji` / `import @kaji/sdk` must work with zero env, and an agent must run end-to-end with in-memory + mock).

- **Phase 1 (Python, `kaji/sdk/`):**
  1. Document/knowledge RAG subsystem (ROADMAP item 14): ingestion → chunking → embedding → in-memory vector store → retrieval-over-corpus. Pluggable backends mirroring the existing `ToolRetriever` `Embedder`/`EmbeddingCache` protocol. Infra-free default.
  2. Durable session persistence (ROADMAP item 16): a `SessionStore` interface in the SDK + a real `list_active` on `SessionManager` (today it returns `[]`).
- **Phase 2 (TypeScript, `kaji/ts/`):** full agent-runtime parity (ROADMAP items 25-28): `ModelProvider` interface + registry + mock provider + `AgentRuntime.runTurn` port + tool-loop glue + settle the sync-vs-async `publish` question (already `async` in `bus.ts:69` — confirm and lock it).

**Reference implementation:** The Python SDK is canonical. The TS port matches its public surface, event names (snake_case wire format), and the tool-lifecycle event sequence (`ToolCallRequested → ToolCallStarted → ToolCallCompleted | ToolCallFailed`).

**Tech stack:** Python 3.11 / Poetry / pytest (SDK). TypeScript / Bun / Vitest / Zod 4 (TS SDK). No new infra dependencies. RAG vector store is pure-Python in-memory cosine (same math as `ToolRetriever.cosine_similarity`).

**Order:** Phase 1 first (both sub-items), then Phase 2. Each phase ships independently green.

---

## Architectural decisions (settle before coding)

These are the load-bearing choices. The /autoplan review should pressure-test them.

### D-A. RAG reuses the `Embedder` protocol, does NOT fork it
`kaji/sdk/kaji/runtime/tools/retriever.py` already defines `Embedder` (async `embed(text) -> List[float]`) and `cosine_similarity`. The document RAG store reuses the *same* `Embedder` protocol so one embedder instance serves both tool-RAG and doc-RAG. The new `VectorStore` is a separate concern (it stores chunked documents, not tool names), but it depends on the existing `Embedder`, not a new one. DRY (principle 4).

### D-B. RAG lives in a new top-level package group `knowledge/`, not under `runtime/tools/`
Tool-RAG (`runtime/tools/retriever.py`) selects *which tool to call*. Document-RAG retrieves *knowledge to ground a response*. Different lifecycle, different consumer. New module: `kaji/sdk/kaji/knowledge/` with `chunking.py`, `store.py`, `rag.py`. This mirrors the existing layering (infra / modalities / runtime are sibling groups). Explicit over clever (principle 5).

### D-C. The RAG retrieval seam is the existing `MemoryRetrieval*` events
Both SDKs already define `MemoryRetrievalStarted` / `MemoryRetrievalCompleted` events (Python `infra/events/schemas.py`; TS `events/schemas.ts:57-66`). Doc-RAG emits these when wired into a runtime, so the event vocabulary already exists. Phase 1 builds the *retrieval capability* and emits these events from a thin helper; full auto-injection into `AgentRuntime` is explicitly OUT of scope (deferred — see NOT in scope) because it touches the reasoning loop and belongs with a broader memory-injection design.

### D-D. `SessionStore` is a NEW protocol distinct from `EventStore`
`EventStore` (`infra/events/store/base.py`) answers "give me the events for ONE session." It cannot answer "list all sessions for a user" — it has no session index. Rather than overload `EventStore` (which would force every backend, including the in-memory test store, to maintain a user→session index), add a separate, optional `SessionStore` protocol:
```python
class SessionStore(Protocol):
    async def list_sessions(self, user_id: str) -> list[SessionRecord]: ...
    async def record_session(self, record: SessionRecord) -> None: ...
```
`SessionManager` takes an optional `SessionStore`. When present, `list_active` delegates to it. When absent (the infra-free default), `list_active` returns `[]` with a one-line "no session store configured" log — the same honest behavior, but now there is a real interface a durable backend (or `kaji-serve`) can implement. Explicit over clever (principle 5); does not break the import-free guarantee.

### D-E. An `InMemorySessionStore` ships so the interface is exercised and testable
Without a concrete implementation the protocol is untested vaporware. Ship `InMemorySessionStore` (a `dict[user_id, list[SessionRecord]]`) so `list_active` has a real, tested path. Durable (Postgres/Redis) backends remain `kaji-serve`'s job. Completeness (principle 1).

### D-F. TS `publish` stays `async`, runtime awaits it
The 2026-06-05 plan said publish "stays sync." That is now stale: `kaji/ts/src/events/bus.ts:69` already returns `Promise<void>`. Keep it async (it is harmless — the body is synchronous fan-out) and have the runtime `await bus.publish(event)`, matching the Python `_emit` which does `await self.bus.publish(event)`. Lock the decision with a doc comment. This resolves item 28 with the *opposite* conclusion the old plan reached, because the code already moved.

---

## File map

### Phase 1a — Document RAG (Python)
| file | status | responsibility |
|------|--------|---------------|
| `kaji/sdk/kaji/knowledge/__init__.py` | create | package exports: `Document`, `Chunk`, `chunk_text`, `VectorStore`, `InMemoryVectorStore`, `DocumentRAG` |
| `kaji/sdk/kaji/knowledge/types.py` | create | `Document` + `Chunk` dataclasses |
| `kaji/sdk/kaji/knowledge/chunking.py` | create | `chunk_text(text, size, overlap)` — deterministic, no deps |
| `kaji/sdk/kaji/knowledge/store.py` | create | `VectorStore` protocol + `InMemoryVectorStore` (cosine search) |
| `kaji/sdk/kaji/knowledge/rag.py` | create | `DocumentRAG` — ties Embedder + VectorStore: `add_document`, `retrieve` |
| `kaji/sdk/kaji/__init__.py` | modify | add knowledge surface to the lazy export map |
| `kaji/sdk/tests/test_knowledge_chunking.py` | create | chunking edge cases (empty, < size, overlap, unicode) |
| `kaji/sdk/tests/test_knowledge_store.py` | create | vector store add/search/top-k/threshold/empty |
| `kaji/sdk/tests/test_knowledge_rag.py` | create | end-to-end RAG with a stub embedder (no network) |

### Phase 1b — Durable session persistence (Python)
| file | status | responsibility |
|------|--------|---------------|
| `kaji/sdk/kaji/runtime/sessions/store.py` | create | `SessionRecord` dataclass + `SessionStore` protocol + `InMemorySessionStore` |
| `kaji/sdk/kaji/runtime/sessions/manager.py` | modify | accept optional `SessionStore`; real `list_active`; record on session creation |
| `kaji/sdk/kaji/__init__.py` | modify | export `SessionStore`, `InMemorySessionStore`, `SessionRecord` |
| `kaji/sdk/tests/test_sessions_store.py` | create | in-memory store: record, list, per-user isolation |
| `kaji/sdk/tests/test_sessions_manager.py` | modify/create | `list_active` returns recorded sessions; empty when no store |

### Phase 2 — TS runtime parity
| file | status | responsibility |
|------|--------|---------------|
| `kaji/ts/src/events/bus.ts` | modify | doc comment locking the async-`publish` decision |
| `kaji/ts/src/providers/base.ts` | create | `ModelProvider`, `ProviderMessage`, `ToolCall`, `ModelResponseChunk`, `ModelResponse` |
| `kaji/ts/src/providers/mock.ts` | create | mock provider: requests first tool, then text |
| `kaji/ts/src/providers/registry.ts` | create | `registerProvider`, `getProvider`, `clearProviders` |
| `kaji/ts/src/providers/index.ts` | create | provider layer re-exports |
| `kaji/ts/src/runtime/cancellation.ts` | create | `CancellationToken` |
| `kaji/ts/src/runtime/context.ts` | create | `buildMessages` — `SessionState.messages` → provider format |
| `kaji/ts/src/runtime/runtime.ts` | create | `AgentRuntime.runTurn` — the ReAct loop |
| `kaji/ts/src/index.ts` | modify | export provider + runtime surface |
| `kaji/ts/tests/providers.mock.test.ts` | create | provider interface + registry + mock |
| `kaji/ts/tests/runtime.test.ts` | create | full `runTurn` loop with mock provider |

> **Note on OpenAI provider:** The 2026-06-05 plan included a TS `OpenAIProvider`. Phase 2 here keeps scope to the *runtime parity milestone* (interface + registry + mock + runtime + tool loop) — the same bar as the Python P0. A real TS provider is a clean follow-up (it has no design risk once the interface lands) and is deferred to keep this plan reviewable. See NOT in scope.

---

## NOT in scope (deferred, with rationale)

- **Auto-injecting doc-RAG into `AgentRuntime`** (Python or TS). The retrieval capability ships; wiring it into the reasoning loop (when to retrieve, how to inject context, dedup with tool-RAG) is a memory-architecture decision that deserves its own design. Building it half-way now would bake in the wrong seam.
- **A real TS LLM provider** (OpenAI/Anthropic). Interface + mock proves the runtime; a real provider is mechanical once the interface is fixed. Deferred to keep the review focused.
- **Durable (Postgres/Redis) `SessionStore` / `VectorStore` backends.** These belong in `kaji-serve`, which is explicitly out of scope this round. The SDK ships the *interfaces* + in-memory implementations so serve can implement them later.
- **Anthropic Python provider, multi-agent router** (ROADMAP 5, 15). Not requested for this build.
- **Persisting documents across restarts.** `InMemoryVectorStore` is process-local by design, matching `InMemoryEventStore` / `InMemoryEmbeddingCache`.

---

## What already exists (leverage map)

| sub-problem | existing code to reuse |
|-------------|------------------------|
| text → vector | `Embedder` protocol + `GeminiEmbedder` (`runtime/tools/retriever.py:30,47`) |
| cosine similarity | `cosine_similarity` (`runtime/tools/retriever.py:21`) — extract to a shared util both RAG and tool-RAG import |
| retrieval events | `MemoryRetrievalStarted/Completed` (Python `infra/events/schemas.py`; TS `events/schemas.ts:57`) |
| session state projection | `ReplaySession` / `replaySession` (Python + TS) |
| event store interface | `EventStore` protocol (`infra/events/store/base.py`) — the model for `SessionStore` |
| TS event bus, store, replay, tool registry | `kaji/ts/src/{events,sessions,tools}/` — all present, runtime plugs into them |
| Python runtime loop to port | `runtime/agents/runtime.py:79` `run_turn` |
| mock provider to port | `runtime/providers/mock.py` |
| tool lifecycle events to emit | `ToolPlanner._execute_single` (`runtime/agents/planner.py:53`) |

---

## Phase 1a — Document RAG

### Task 1: Extract `cosine_similarity` to a shared util

DRY: tool-RAG and doc-RAG both need it. Today it lives inside `retriever.py`. Move it to `kaji/sdk/kaji/knowledge/` is wrong (tool-RAG would then depend on knowledge). Put it in a neutral home both import.

**Files:**
- Create: `kaji/sdk/kaji/runtime/tools/_vector_math.py` (neutral, low-level)
- Modify: `kaji/sdk/kaji/runtime/tools/retriever.py` (import from new util)

- [ ] **Step 1: Write the failing test**

Create `kaji/sdk/tests/test_vector_math.py`:
```python
from kaji.runtime.tools._vector_math import cosine_similarity


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_orthogonal_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_zero_vector_scores_zero_not_nan():
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
```

- [ ] **Step 2: Run test, verify it fails** (`No module named ... _vector_math`)
```bash
cd kaji/sdk && poetry run pytest tests/test_vector_math.py
```

- [ ] **Step 3: Create `_vector_math.py`** — move the exact function body from `retriever.py:21-27`:
```python
"""Shared vector math for RAG (tool selection and document retrieval)."""

import math
from typing import List


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(a * a for a in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)
```

- [ ] **Step 4: Update `retriever.py`** — replace the local def with an import. Keep a re-export so any external caller of `retriever.cosine_similarity` still works:
```python
from kaji.runtime.tools._vector_math import cosine_similarity  # re-exported
```
Delete the old inline `def cosine_similarity` and its `import math` if now unused.

- [ ] **Step 5: Run the full tool-RAG suite to confirm no regression**
```bash
cd kaji/sdk && poetry run pytest tests/test_tools_retriever.py tests/test_vector_math.py
```
Expected: all pass.

- [ ] **Step 6: Commit**
```bash
git add kaji/sdk/kaji/runtime/tools/_vector_math.py kaji/sdk/kaji/runtime/tools/retriever.py kaji/sdk/tests/test_vector_math.py
git commit -m "refactor(sdk): extract cosine_similarity to shared _vector_math"
```

---

### Task 2: Document + Chunk types and chunking

**Files:**
- Create: `kaji/sdk/kaji/knowledge/__init__.py` (start minimal, grow per task)
- Create: `kaji/sdk/kaji/knowledge/types.py`
- Create: `kaji/sdk/kaji/knowledge/chunking.py`
- Create: `kaji/sdk/tests/test_knowledge_chunking.py`

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_knowledge_chunking.py`:
```python
from kaji.knowledge.chunking import chunk_text


def test_short_text_is_one_chunk():
    chunks = chunk_text("hello world", size=100, overlap=0)
    assert chunks == ["hello world"]


def test_empty_text_yields_no_chunks():
    assert chunk_text("", size=100, overlap=0) == []


def test_whitespace_only_yields_no_chunks():
    assert chunk_text("   \n  ", size=100, overlap=0) == []


def test_long_text_splits_by_size():
    text = "a" * 250
    chunks = chunk_text(text, size=100, overlap=0)
    assert len(chunks) == 3
    assert chunks[0] == "a" * 100
    assert chunks[2] == "a" * 50


def test_overlap_repeats_tail():
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, size=5, overlap=2)
    # window slides by (size - overlap) = 3
    assert chunks[0] == "abcde"
    assert chunks[1] == "defgh"
    assert chunks[2] == "ghij"


def test_overlap_must_be_less_than_size():
    import pytest
    with pytest.raises(ValueError):
        chunk_text("abc", size=5, overlap=5)
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_chunking.py
```

- [ ] **Step 3: Create `types.py`**
```python
"""Document and chunk types for the knowledge/RAG subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Document:
    """A source document to be ingested into the vector store."""

    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
    """A chunk of a document, the unit of retrieval."""

    document_id: str
    text: str
    index: int  # position within the source document
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: List[float] = field(default_factory=list)
```

- [ ] **Step 4: Create `chunking.py`**
```python
"""Deterministic, dependency-free text chunking.

A character-window chunker with overlap. Deterministic so tests are stable and
the same document always produces the same chunks (and therefore the same
cache keys downstream). Token-aware chunking can be layered later behind the
same function signature.
"""

from typing import List


def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> List[str]:
    """Split ``text`` into overlapping character windows.

    Args:
        text: the source text. Empty/whitespace-only yields ``[]``.
        size: max characters per chunk. Must be > 0.
        overlap: characters shared between consecutive chunks. Must be < size.

    Returns:
        A list of chunk strings in document order.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap >= size:
        raise ValueError("overlap must be less than size")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")

    stripped = text.strip()
    if not stripped:
        return []

    step = size - overlap
    chunks: List[str] = []
    start = 0
    n = len(stripped)
    while start < n:
        chunks.append(stripped[start : start + size])
        start += step
    return chunks
```

- [ ] **Step 5: Create minimal `__init__.py`**
```python
"""Kaji knowledge subsystem: document ingestion and retrieval (RAG)."""

from kaji.knowledge.chunking import chunk_text
from kaji.knowledge.types import Chunk, Document

__all__ = ["chunk_text", "Chunk", "Document"]
```

- [ ] **Step 6: Run, verify pass**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_chunking.py
```

- [ ] **Step 7: Commit**
```bash
git add kaji/sdk/kaji/knowledge/ kaji/sdk/tests/test_knowledge_chunking.py
git commit -m "feat(sdk): add knowledge types and deterministic text chunking"
```

---

### Task 3: VectorStore protocol + InMemoryVectorStore

**Files:**
- Create: `kaji/sdk/kaji/knowledge/store.py`
- Create: `kaji/sdk/tests/test_knowledge_store.py`

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_knowledge_store.py`:
```python
import pytest

from kaji.knowledge.store import InMemoryVectorStore
from kaji.knowledge.types import Chunk


def _chunk(doc_id: str, text: str, idx: int, vec: list[float]) -> Chunk:
    return Chunk(document_id=doc_id, text=text, index=idx, embedding=vec)


@pytest.mark.asyncio
async def test_add_and_search_returns_nearest():
    store = InMemoryVectorStore()
    await store.add([
        _chunk("d1", "cats", 0, [1.0, 0.0]),
        _chunk("d1", "dogs", 1, [0.0, 1.0]),
    ])
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
    await store.add([
        _chunk("d", "a", 0, [1.0, 0.0]),
        _chunk("d", "b", 1, [0.9, 0.1]),
        _chunk("d", "c", 2, [0.8, 0.2]),
    ])
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
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_store.py
```

- [ ] **Step 3: Create `store.py`**
```python
"""Vector store for document chunks. Infra-free in-memory default.

The protocol mirrors the spirit of ``EventStore``: a narrow interface a durable
backend (pgvector, etc., in kaji-serve) can implement later. The bundled
``InMemoryVectorStore`` does an exact cosine scan — fine for embedded use and
tests, not for millions of chunks.
"""

from typing import List, Protocol

from kaji.knowledge.types import Chunk
from kaji.runtime.tools._vector_math import cosine_similarity


class VectorStore(Protocol):
    """Stores embedded chunks and returns the nearest by cosine similarity."""

    async def add(self, chunks: List[Chunk]) -> None:
        ...

    async def search(
        self, query_embedding: List[float], top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        ...


class InMemoryVectorStore:
    """Process-local exact-cosine vector store. Lost on restart."""

    def __init__(self) -> None:
        self._chunks: List[Chunk] = []

    async def add(self, chunks: List[Chunk]) -> None:
        # Only keep chunks that carry an embedding; an empty vector can never match.
        self._chunks.extend(c for c in chunks if c.embedding)

    async def search(
        self, query_embedding: List[float], top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        if not query_embedding or not self._chunks:
            return []
        dim = len(query_embedding)
        scored = []
        for c in self._chunks:
            # H4: cosine_similarity uses zip(), which silently truncates on a
            # dimension mismatch. Skip chunks whose embedding dim differs from
            # the query's (e.g. the embedder was swapped under a populated store)
            # rather than returning a garbage score.
            if len(c.embedding) != dim:
                logger.warning(
                    "Skipping chunk %s/%d: embedding dim %d != query dim %d",
                    c.document_id, c.index, len(c.embedding), dim,
                )
                continue
            scored.append((cosine_similarity(query_embedding, c.embedding), c))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [c for score, c in scored[:top_k] if score >= threshold]
```

> **Eng H4 fix applied above.** Add `import logging` + `logger = logging.getLogger(__name__)` to `store.py`. Add a test to `test_knowledge_store.py`: add a 2-d chunk and a 3-d chunk, search with a 2-d query, assert only the 2-d chunk can match (the 3-d one is skipped, not truncated).

- [ ] **Step 4: Run, verify pass**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_store.py
```

- [ ] **Step 5: Commit**
```bash
git add kaji/sdk/kaji/knowledge/store.py kaji/sdk/tests/test_knowledge_store.py
git commit -m "feat(sdk): add VectorStore protocol and InMemoryVectorStore"
```

---

### Task 4: DocumentRAG — tie embedder + store

**Files:**
- Create: `kaji/sdk/kaji/knowledge/rag.py`
- Modify: `kaji/sdk/kaji/knowledge/__init__.py`
- Create: `kaji/sdk/tests/test_knowledge_rag.py`

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_knowledge_rag.py`:
```python
import pytest

from kaji.knowledge.rag import DocumentRAG
from kaji.knowledge.store import InMemoryVectorStore
from kaji.knowledge.types import Document


class StubEmbedder:
    """Deterministic 2-D embedder: maps a keyword to an axis. No network."""

    async def embed(self, text: str) -> list[float]:
        t = text.lower()
        cat = 1.0 if "cat" in t else 0.0
        dog = 1.0 if "dog" in t else 0.0
        if cat == 0.0 and dog == 0.0:
            return []  # mimic "no embedding" path
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
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_rag.py
```

- [ ] **Step 3: Create `rag.py`**
```python
"""Document RAG: ingest documents, retrieve relevant chunks for a query.

Infra-free by default: the embedder defaults to the same lazily-constructed
``GeminiEmbedder`` the tool retriever uses (returns ``[]`` with no key, so the
whole thing degrades to "stores nothing / retrieves nothing" rather than
raising). Inject any ``Embedder`` and ``VectorStore`` to swap backends.

This builds the retrieval *capability*. Auto-injecting retrieved context into
``AgentRuntime`` (when to retrieve, how to ground the prompt) is intentionally
left to a future memory-injection design — see the plan's NOT-in-scope section.
"""

import logging
from typing import List, Optional

from kaji.knowledge.chunking import chunk_text
from kaji.knowledge.store import InMemoryVectorStore, VectorStore
from kaji.knowledge.types import Chunk, Document
from kaji.runtime.tools.retriever import Embedder, GeminiEmbedder

logger = logging.getLogger(__name__)


class DocumentRAG:
    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> None:
        self._embedder: Embedder = embedder or GeminiEmbedder()
        self._store: VectorStore = store or InMemoryVectorStore()
        self._chunk_size = chunk_size
        self._overlap = overlap

    async def add_document(
        self,
        document: Document,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
    ) -> int:
        """Chunk, embed, and store a document. Returns the number of chunks stored."""
        size = chunk_size if chunk_size is not None else self._chunk_size
        ov = overlap if overlap is not None else self._overlap
        pieces = chunk_text(document.text, size=size, overlap=ov)

        chunks: List[Chunk] = []
        for i, piece in enumerate(pieces):
            try:
                vec = await self._embedder.embed(piece)
            except Exception as e:  # embedder failure must not crash ingestion
                logger.warning("Embedding failed for %s chunk %d: %s", document.id, i, e)
                vec = []
            if not vec:
                continue
            chunks.append(
                Chunk(
                    document_id=document.id,
                    text=piece,
                    index=i,
                    metadata=dict(document.metadata),
                    embedding=vec,
                )
            )

        await self._store.add(chunks)
        # DX F3: a silent 0 from non-empty text almost always means "no embedder
        # configured" (e.g. GEMINI_API_KEY unset -> GeminiEmbedder returns []).
        # Surface it as problem + cause + fix rather than letting the dev wonder.
        if not chunks and pieces:
            logger.warning(
                "DocumentRAG.add_document stored 0 of %d chunks for %r: the embedder "
                "returned no vectors. Set GEMINI_API_KEY or pass embedder=... to "
                "DocumentRAG(...).",
                len(pieces), document.id,
            )
        return len(chunks)

    async def retrieve(
        self, query: str, top_k: int = 5, threshold: float = 0.0
    ) -> List[Chunk]:
        """Return the chunks most relevant to ``query`` (possibly empty)."""
        try:
            query_vec = await self._embedder.embed(query)
        except Exception as e:
            logger.error("Failed to embed RAG query: %s", e)
            return []
        if not query_vec:
            return []
        return await self._store.search(query_vec, top_k=top_k, threshold=threshold)
```

- [ ] **Step 4: Expand `knowledge/__init__.py`**
```python
"""Kaji knowledge subsystem: document ingestion and retrieval (RAG)."""

from kaji.knowledge.chunking import chunk_text
from kaji.knowledge.rag import DocumentRAG
from kaji.knowledge.store import InMemoryVectorStore, VectorStore
from kaji.knowledge.types import Chunk, Document

__all__ = [
    "chunk_text",
    "Chunk",
    "Document",
    "VectorStore",
    "InMemoryVectorStore",
    "DocumentRAG",
]
```

- [ ] **Step 5: Run, verify pass**
```bash
cd kaji/sdk && poetry run pytest tests/test_knowledge_rag.py
```

- [ ] **Step 6: Commit**
```bash
git add kaji/sdk/kaji/knowledge/rag.py kaji/sdk/kaji/knowledge/__init__.py kaji/sdk/tests/test_knowledge_rag.py
git commit -m "feat(sdk): add DocumentRAG (ingest + retrieve), infra-free default"
```

---

### Task 5: Export knowledge surface from the SDK public API

**Files:**
- Modify: `kaji/sdk/kaji/__init__.py`

- [ ] **Step 1: Read the lazy export map**
```bash
cd kaji/sdk && grep -n "knowledge\|DocumentRAG\|_LAZY\|__getattr__" kaji/__init__.py | head
```
Match the existing lazy-import style (the file maps public names to module paths and constructs on first attribute access — do NOT add eager imports, that breaks the infra-free guarantee).

- [ ] **Step 2: Add `DocumentRAG`, `Document`, `Chunk`, `InMemoryVectorStore`, `VectorStore`, `chunk_text`** to the lazy map, pointing at `kaji.knowledge.*`.

- [ ] **Step 3: Verify import stays infra-free** (no env set):
```bash
cd kaji/sdk && poetry run python -c "import kaji; print(kaji.DocumentRAG, kaji.Document, kaji.chunk_text)"
```
Expected: prints the three objects, no exception, no env required.

- [ ] **Step 4: Run the whole SDK suite**
```bash
cd kaji/sdk && poetry run pytest tests/ -q
```
Expected: all green (83 prior + new knowledge tests).

- [ ] **Step 5: Commit**
```bash
git add kaji/sdk/kaji/__init__.py
git commit -m "feat(sdk): export knowledge/RAG surface from public API"
```

---

## Phase 1b — Durable session persistence

### Task 6: SessionStore protocol + InMemorySessionStore

**Files:**
- Create: `kaji/sdk/kaji/runtime/sessions/store.py`
- Create: `kaji/sdk/tests/test_sessions_store.py`

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_sessions_store.py`:
```python
import pytest

from kaji.runtime.sessions.store import InMemorySessionStore, SessionRecord


@pytest.mark.asyncio
async def test_record_and_list_for_user():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    sessions = await store.list_sessions("u1")
    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"


@pytest.mark.asyncio
async def test_users_are_isolated():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    await store.record_session(SessionRecord(session_id="s2", user_id="u2"))
    assert len(await store.list_sessions("u1")) == 1
    assert len(await store.list_sessions("u2")) == 1
    assert await store.list_sessions("u3") == []


@pytest.mark.asyncio
async def test_recording_same_session_is_idempotent():
    store = InMemorySessionStore()
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    await store.record_session(SessionRecord(session_id="s1", user_id="u1"))
    assert len(await store.list_sessions("u1")) == 1
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/sdk && poetry run pytest tests/test_sessions_store.py
```

- [ ] **Step 3: Create `store.py`**
```python
"""Session index: list sessions per user.

``EventStore`` answers "events for one session" but has no cross-session index,
so it cannot list a user's sessions. ``SessionStore`` is a separate, optional
protocol for that. Keeping it separate means the infra-free ``InMemoryEventStore``
does not have to maintain a user->session map it never needs.

The bundled ``InMemorySessionStore`` is process-local. A durable backend
(Postgres in kaji-serve) implements the same protocol later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Protocol


@dataclass
class SessionRecord:
    """A row in the session index."""

    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    title: str = ""


class SessionStore(Protocol):
    """Cross-session index, keyed by user."""

    async def record_session(self, record: SessionRecord) -> None:
        ...

    async def list_sessions(self, user_id: str) -> List[SessionRecord]:
        ...


class InMemorySessionStore:
    """Process-local session index. Lost on restart."""

    def __init__(self) -> None:
        self._by_user: Dict[str, Dict[str, SessionRecord]] = {}

    async def record_session(self, record: SessionRecord) -> None:
        bucket = self._by_user.setdefault(record.user_id, {})
        bucket.setdefault(record.session_id, record)  # idempotent on session_id

    async def list_sessions(self, user_id: str) -> List[SessionRecord]:
        bucket = self._by_user.get(user_id, {})
        return sorted(bucket.values(), key=lambda r: r.created_at, reverse=True)
```

- [ ] **Step 4: Run, verify pass**
```bash
cd kaji/sdk && poetry run pytest tests/test_sessions_store.py
```

- [ ] **Step 5: Commit**
```bash
git add kaji/sdk/kaji/runtime/sessions/store.py kaji/sdk/tests/test_sessions_store.py
git commit -m "feat(sdk): add SessionStore protocol and InMemorySessionStore"
```

---

### Task 7: Wire SessionStore into SessionManager

**Files:**
- Modify: `kaji/sdk/kaji/runtime/sessions/manager.py`
- Create: `kaji/sdk/tests/test_sessions_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `kaji/sdk/tests/test_sessions_manager.py`:
```python
import pytest

from kaji.infra.events.store.inmem import InMemoryEventStore
from kaji.infra.events.schemas import UserMessage
from kaji.runtime.sessions.manager import SessionManager
from kaji.runtime.sessions.store import InMemorySessionStore, SessionRecord


@pytest.mark.asyncio
async def test_list_active_empty_without_store():
    mgr = SessionManager(InMemoryEventStore())
    assert await mgr.list_active("u1") == []


@pytest.mark.asyncio
async def test_list_active_returns_recorded_sessions():
    sessions = InMemorySessionStore()
    await sessions.record_session(SessionRecord(session_id="s1", user_id="u1"))
    mgr = SessionManager(InMemoryEventStore(), session_store=sessions)
    active = await mgr.list_active("u1")
    assert len(active) == 1
    assert active[0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_get_state_still_works():
    store = InMemoryEventStore()
    await store.append(UserMessage(session_id="s1", content="hi"))
    mgr = SessionManager(store)
    state = await mgr.get_state("s1")
    assert state is not None
```

- [ ] **Step 2: Run, verify fail** (constructor doesn't accept `session_store` yet)
```bash
cd kaji/sdk && poetry run pytest tests/test_sessions_manager.py
```

- [ ] **Step 3: Rewrite `manager.py`**
```python
"""Session lifecycle coordinator."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kaji.infra.events.store import EventStore
from kaji.runtime.sessions.replay import ReplaySession
from kaji.runtime.sessions.state import SessionState
from kaji.runtime.sessions.store import SessionRecord, SessionStore

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session projections over the append-only event log.

    Pass an optional ``SessionStore`` to enable ``list_active``. Without one,
    ``list_active`` returns ``[]`` (the SDK ships no durable index by default —
    that lives in kaji-serve).
    """

    def __init__(
        self, store: EventStore, session_store: Optional[SessionStore] = None
    ) -> None:
        self._store = store
        self._session_store = session_store

    async def get_state(self, session_id: str) -> SessionState:
        events = await self._store.get_events(session_id)
        return ReplaySession(events)

    async def record_session(self, session_id: str, user_id: str, title: str = "") -> None:
        """Register a session in the index, if a session store is configured."""
        if self._session_store is None:
            return
        await self._session_store.record_session(
            SessionRecord(session_id=session_id, user_id=user_id, title=title)
        )

    async def list_active(self, user_id: str) -> list[dict[str, Any]]:
        """List a user's sessions. Empty if no session store is configured."""
        if self._session_store is None:
            logger.debug("list_active called with no session store; returning []")
            return []
        records = await self._session_store.list_sessions(user_id)
        return [
            {
                "session_id": r.session_id,
                "user_id": r.user_id,
                "created_at": r.created_at,
                "title": r.title,
            }
            for r in records
        ]
```

- [ ] **Step 4: Run, verify pass**
```bash
cd kaji/sdk && poetry run pytest tests/test_sessions_manager.py
```

- [ ] **Step 4b: Wire `record_session` so persistence is genuinely exercised (Eng M5 fix).** A `record_session` method that nothing calls leaves `list_active` always-empty in real flows — the same bug, relocated. Add a recording call at the one place a session is born. Add this test to `test_sessions_manager.py`:
```python
@pytest.mark.asyncio
async def test_recording_then_listing_round_trips():
    sessions = InMemorySessionStore()
    mgr = SessionManager(InMemoryEventStore(), session_store=sessions)
    await mgr.record_session("s9", "u1", title="chat")
    active = await mgr.list_active("u1")
    assert [s["session_id"] for s in active] == ["s9"]
    assert active[0]["title"] == "chat"
```
`record_session` is already on `SessionManager` (Step 3). This test proves the round-trip through the manager (not just the store in isolation), so the ROADMAP-16 "real `list_active`" claim is backed by an exercised path. NOTE: auto-recording from inside `AgentRuntime` is deliberately NOT done here (the runtime has no `user_id` and no `SessionManager` reference; coupling them is a larger change). The honest claim is "callable + round-trip-tested via SessionManager," reflected in the softened ROADMAP wording (Task 12).

- [ ] **Step 5: Export the session-store surface** — add `SessionStore`, `InMemorySessionStore`, `SessionRecord` to `kaji/__init__.py` lazy map (same style as Task 5). Verify:
```bash
cd kaji/sdk && poetry run python -c "import kaji; print(kaji.SessionStore, kaji.InMemorySessionStore, kaji.SessionRecord)"
```

- [ ] **Step 6: Full SDK suite**
```bash
cd kaji/sdk && poetry run pytest tests/ -q
```
Expected: all green.

- [ ] **Step 7: Commit**
```bash
git add kaji/sdk/kaji/runtime/sessions/manager.py kaji/sdk/kaji/__init__.py kaji/sdk/tests/test_sessions_manager.py
git commit -m "feat(sdk): wire SessionStore into SessionManager.list_active"
```

---

## Phase 2 — TypeScript runtime parity

### Task 7.5: Thread real `tool_call_id` through replay (Eng H3 fix — do BEFORE the runtime)

**Files:**
- Modify: `kaji/ts/src/sessions/replay.ts`

The runtime emits tool calls with real ids (`tc.id`), but `replay.ts`'s `Message` only stores `{role, content, name}` — the id is discarded, so `buildMessages` later fabricates one from the tool name. That breaks any real provider (OpenAI/Anthropic reject a tool result whose `tool_call_id` doesn't match the request) and collides when the same tool is called twice. Fix the data model now, before the runtime depends on it.

- [ ] **Step 1: Add `toolCallId` to `Message` and project it**

In `kaji/ts/src/sessions/replay.ts`, extend the `Message` interface:
```ts
export interface Message {
  role: "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool messages. */
  name?: string;
  /** Set only for tool messages: the id from the originating tool call request. */
  toolCallId?: string;
}
```

In the `TOOL_CALL_COMPLETED` case, carry the id through:
```ts
      case EventType.TOOL_CALL_COMPLETED:
        state.messages.push({
          role: "tool",
          name: event.tool_name,
          content: stringifyResult(event.result),
          toolCallId: event.tool_call_id,
        });
        break;
```

Add a comment above the `AGENT_MESSAGE_DELTA`/transient cases noting they must NOT be projected (the mock provider's termination depends on only `AGENT_MESSAGE_COMPLETED`→assistant and `TOOL_CALL_COMPLETED`→tool appearing in history; projecting deltas would loop forever).

- [ ] **Step 2: Add a regression test** to `kaji/ts/tests/replay.test.ts`: a `TOOL_CALL_COMPLETED` event with `tool_call_id: "call_abc"` projects a tool message with `toolCallId === "call_abc"`.

- [ ] **Step 3: Run + commit**
```bash
cd kaji/ts && bun run test tests/replay.test.ts
git add kaji/ts/src/sessions/replay.ts kaji/ts/tests/replay.test.ts
git commit -m "fix(ts): preserve real tool_call_id through session replay"
```

---

### Task 8: Lock the async-`publish` decision

**Files:**
- Modify: `kaji/ts/src/events/bus.ts`

The 2026-06-05 plan claimed publish would stay *sync*. The code has since moved: `bus.ts:69` already declares `async publish(...): Promise<void>`. The body is synchronous fan-out, so `async` is harmless and lets callers `await` it uniformly. Keep it async (matches Python `await self.bus.publish(...)`); lock it with a comment.

- [ ] **Step 1: Add the decision comment.** Edit `kaji/ts/src/events/bus.ts`, replacing the existing `/** Publish an event to every subscriber of its session. */` above `async publish` with:
```ts
  /**
   * Publish an event to every subscriber of its session.
   *
   * Intentionally `async` (returns a resolved Promise): the body is synchronous
   * fan-out via `Subscription.push`, but an async signature lets every caller
   * `await bus.publish(...)` uniformly — matching the Python runtime's
   * `await self.bus.publish(event)`. The agent runtime depends on this shape.
   */
```

- [ ] **Step 2: Confirm nothing broke**
```bash
cd kaji/ts && bun run test && bun run typecheck
```
Expected: existing tests pass, no type errors.

- [ ] **Step 3: Commit**
```bash
git add kaji/ts/src/events/bus.ts
git commit -m "docs(ts): lock async publish decision in EventBus"
```

---

### Task 9: Provider interface, types, registry, and mock

**Files:**
- Create: `kaji/ts/src/providers/base.ts`
- Create: `kaji/ts/src/providers/registry.ts`
- Create: `kaji/ts/src/providers/mock.ts`
- Create: `kaji/ts/src/providers/index.ts`
- Create: `kaji/ts/tests/providers.mock.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `kaji/ts/tests/providers.mock.test.ts`:
```ts
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import type {
  ModelProvider,
  ModelResponseChunk,
  ProviderMessage,
} from "../src/providers/base";
import { MockProvider } from "../src/providers/mock";
import {
  clearProviders,
  getProvider,
  registerProvider,
} from "../src/providers/registry";
import { toolSpecFromSchema } from "../src/tools/registry";

afterEach(() => clearProviders());

describe("provider registry", () => {
  it("registers and retrieves by name", () => {
    const p = new MockProvider();
    registerProvider("mock", p);
    expect(getProvider("mock")).toBe(p);
  });

  it("throws on duplicate registration", () => {
    registerProvider("dup", new MockProvider());
    expect(() => registerProvider("dup", new MockProvider())).toThrow(
      /already registered/,
    );
  });

  it("throws on unknown provider", () => {
    expect(() => getProvider("nope")).toThrow(/Unknown provider/);
  });
});

describe("MockProvider", () => {
  const weather = toolSpecFromSchema(
    "get_weather",
    "Look up weather",
    z.object({ city: z.string() }),
  );

  it("requests the first tool when no tool result is in history", async () => {
    const messages: ProviderMessage[] = [{ role: "user", content: "weather?" }];
    const r = await new MockProvider().generate(messages, [weather]);
    expect(r.toolCalls).toHaveLength(1);
    expect(r.toolCalls[0]?.name).toBe("get_weather");
    expect(r.content).toBe("");
  });

  it("returns text once a tool result is present", async () => {
    const messages: ProviderMessage[] = [
      { role: "user", content: "weather?" },
      { role: "tool", name: "get_weather", content: '{"tempF":68}', tool_call_id: "c1" },
    ];
    const r = await new MockProvider().generate(messages, [weather]);
    expect(r.toolCalls).toHaveLength(0);
    expect(r.content.length).toBeGreaterThan(0);
  });

  it("returns text immediately with no tools", async () => {
    const r = await new MockProvider().generate(
      [{ role: "user", content: "hi" }],
      [],
    );
    expect(r.toolCalls).toHaveLength(0);
  });

  it("generateStream yields one chunk equal to generate", async () => {
    const chunks: ModelResponseChunk[] = [];
    for await (const c of new MockProvider().generateStream(
      [{ role: "user", content: "hi" }],
      [],
    )) {
      chunks.push(c);
    }
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.toolCalls).toHaveLength(0);
  });

  it("satisfies the ModelProvider interface", () => {
    const p: ModelProvider = new MockProvider();
    expect(p).toBeDefined();
  });
});
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/ts && bun run test tests/providers.mock.test.ts
```

- [ ] **Step 3: Create `base.ts`**
```ts
/**
 * Provider interface for LLM backends, mirroring
 * `kaji.runtime.providers.base.ModelProvider`.
 *
 * Each provider translates the neutral message + tool format to its own API at
 * its boundary. The runtime never imports provider-specific types.
 */
import type { ToolSpec } from "../tools/registry";

/** A message in the conversation history passed to the provider. */
export interface ProviderMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  /** Set only for tool-result messages. */
  name?: string;
  /** Set only for tool-result messages: id from the originating tool call. */
  tool_call_id?: string;
}

/** A tool call the model wants to make. */
export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

/** A streaming chunk from the provider. */
export interface ModelResponseChunk {
  delta: string;
  toolCalls: ToolCall[];
}

/** A complete non-streaming response. */
export interface ModelResponse {
  content: string;
  toolCalls: ToolCall[];
}

/** Common interface every LLM provider implements. */
export interface ModelProvider {
  generate(messages: ProviderMessage[], tools: ToolSpec[]): Promise<ModelResponse>;
  generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk>;
}
```

- [ ] **Step 4: Create `registry.ts`**
```ts
/**
 * Provider registry: a process-level map from name to `ModelProvider`.
 * Mirrors `kaji.runtime.providers.registry`.
 */
import type { ModelProvider } from "./base";

const providers = new Map<string, ModelProvider>();

export function registerProvider(name: string, provider: ModelProvider): void {
  if (providers.has(name)) {
    throw new Error(`Provider already registered: ${name}`);
  }
  providers.set(name, provider);
}

export function getProvider(name: string): ModelProvider {
  const p = providers.get(name);
  if (p === undefined) {
    throw new Error(
      `Unknown provider: ${name}. Register it with registerProvider() first.`,
    );
  }
  return p;
}

/** Clear all registrations. For tests. */
export function clearProviders(): void {
  providers.clear();
}
```

- [ ] **Step 5: Create `mock.ts`**
```ts
/**
 * Mock LLM provider, mirroring `kaji.runtime.providers.mock`.
 *
 * If tools are offered and no tool result is yet in history, it calls the first
 * tool with empty args; otherwise it returns a fixed text response. This drives
 * the full tool loop without a network call.
 */
import type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
} from "./base";
import type { ToolSpec } from "../tools/registry";

const FINAL_TEXT = "The mock provider has completed the tool loop.";

function hasToolResult(messages: ProviderMessage[]): boolean {
  return messages.some((m) => m.role === "tool");
}

export class MockProvider implements ModelProvider {
  async generate(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): Promise<ModelResponse> {
    const first = tools[0];
    if (first !== undefined && !hasToolResult(messages)) {
      return { content: "", toolCalls: [{ id: "mock-call-1", name: first.name, args: {} }] };
    }
    return { content: FINAL_TEXT, toolCalls: [] };
  }

  async *generateStream(
    messages: ProviderMessage[],
    tools: ToolSpec[],
  ): AsyncGenerator<ModelResponseChunk> {
    const result = await this.generate(messages, tools);
    yield { delta: result.content, toolCalls: result.toolCalls };
  }
}
```

- [ ] **Step 6: Create `index.ts`**
```ts
export type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "./base";
export { MockProvider } from "./mock";
export { clearProviders, getProvider, registerProvider } from "./registry";
```

- [ ] **Step 7: Run, verify pass**
```bash
cd kaji/ts && bun run test tests/providers.mock.test.ts
```

- [ ] **Step 8: Commit**
```bash
git add kaji/ts/src/providers/ kaji/ts/tests/providers.mock.test.ts
git commit -m "feat(ts): add ModelProvider interface, registry, and MockProvider"
```

---

### Task 10: CancellationToken, buildMessages, and AgentRuntime

**Files:**
- Create: `kaji/ts/src/runtime/cancellation.ts`
- Create: `kaji/ts/src/runtime/context.ts`
- Create: `kaji/ts/src/runtime/runtime.ts`
- Create: `kaji/ts/tests/runtime.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `kaji/ts/tests/runtime.test.ts`:
```ts
import { afterEach, describe, expect, it } from "vitest";
import { z } from "zod";

import { KajiEvent, EventType } from "../src/events/schemas";
import { EventBus } from "../src/events/bus";
import { InMemoryEventStore } from "../src/events/store";
import { MockProvider } from "../src/providers/mock";
import { CancellationToken } from "../src/runtime/cancellation";
import { buildMessages } from "../src/runtime/context";
import { AgentRuntime } from "../src/runtime/runtime";
import {
  clearTools,
  registerTool,
  toolSpecFromSchema,
} from "../src/tools/registry";
import type { Message } from "../src/sessions/replay";

afterEach(() => clearTools());

describe("CancellationToken", () => {
  it("starts not cancelled, flips on cancel", () => {
    const t = new CancellationToken();
    expect(t.isCancelled).toBe(false);
    t.cancel();
    expect(t.isCancelled).toBe(true);
  });

  it("throwIfCancelled throws after cancel", () => {
    const t = new CancellationToken();
    t.cancel();
    expect(() => t.throwIfCancelled()).toThrow(/cancelled/);
  });
});

describe("buildMessages", () => {
  it("prepends a system message when given a prompt", () => {
    const msgs: Message[] = [{ role: "user", content: "hello" }];
    const r = buildMessages(msgs, "You are helpful.");
    expect(r[0]).toEqual({ role: "system", content: "You are helpful." });
    expect(r[1]?.role).toBe("user");
  });

  it("omits system message when no prompt", () => {
    const r = buildMessages([{ role: "user", content: "hi" }]);
    expect(r).toHaveLength(1);
  });

  it("uses the real toolCallId when present (H3)", () => {
    const r = buildMessages([
      { role: "tool", content: '{"x":1}', name: "get_weather", toolCallId: "call_abc" },
    ]);
    expect(r[0]).toEqual({
      role: "tool",
      content: '{"x":1}',
      name: "get_weather",
      tool_call_id: "call_abc",
    });
  });

  it("falls back to name only when no toolCallId is present", () => {
    const r = buildMessages([{ role: "tool", content: "{}", name: "legacy" }]);
    expect(r[0]?.tool_call_id).toBe("legacy");
  });
});

describe("AgentRuntime.runTurn", () => {
  function setup() {
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });
    return { store, bus, runtime };
  }

  async function seed(store: InMemoryEventStore, sessionId: string) {
    await store.append(
      KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: sessionId }),
    );
    await store.append(
      KajiEvent.parse({
        type: EventType.USER_MESSAGE,
        session_id: sessionId,
        content: "hello",
      }),
    );
  }

  async function collectUntilCompleted(bus: EventBus, sessionId: string) {
    const got: KajiEvent[] = [];
    const sub = bus.subscribe(sessionId);
    const done = (async () => {
      for await (const e of sub) {
        got.push(e);
        if (e.type === EventType.AGENT_MESSAGE_COMPLETED) break;
      }
    })();
    return { got, done };
  }

  it("emits AgentMessageCompleted with no tools registered", async () => {
    const { store, bus, runtime } = setup();
    const s = "s-no-tools";
    await seed(store, s);
    const { got, done } = await collectUntilCompleted(bus, s);
    await runtime.runTurn(s);
    await done;
    expect(got.some((e) => e.type === EventType.AGENT_MESSAGE_COMPLETED)).toBe(true);
  });

  it("emits the tool lifecycle then completion for one tool call", async () => {
    const { store, bus, runtime } = setup();
    const s = "s-tool";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("get_weather", "weather", z.object({ city: z.string() })),
      async () => ({ tempF: 68 }),
    );
    const { got, done } = await collectUntilCompleted(bus, s);
    await runtime.runTurn(s);
    await done;
    const types = got.map((e) => e.type);
    expect(types).toContain(EventType.TOOL_CALL_REQUESTED);
    expect(types).toContain(EventType.TOOL_CALL_STARTED);
    expect(types).toContain(EventType.TOOL_CALL_COMPLETED);
    expect(types).toContain(EventType.AGENT_MESSAGE_COMPLETED);
    expect(types.indexOf(EventType.TOOL_CALL_REQUESTED)).toBeLessThan(
      types.indexOf(EventType.TOOL_CALL_COMPLETED),
    );
  });

  it("emits ToolCallFailed when a tool throws", async () => {
    const { store, bus, runtime } = setup();
    const s = "s-fail";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("bad", "fails", z.object({})),
      async () => {
        throw new Error("boom");
      },
    );
    const { got, done } = await collectUntilCompleted(bus, s);
    await runtime.runTurn(s);
    await done;
    expect(got.some((e) => e.type === EventType.TOOL_CALL_FAILED)).toBe(true);
  });

  it("rejects when cancelled before the loop", async () => {
    const { store, runtime } = setup();
    const s = "s-cancel";
    await seed(store, s);
    const token = new CancellationToken();
    token.cancel();
    await expect(runtime.runTurn(s, { cancellationToken: token })).rejects.toThrow(
      /cancelled/,
    );
  });

  it("does NOT emit an empty completion on max-iteration exhaustion (C1)", async () => {
    // A provider that ALWAYS requests a tool forces the loop to exhaust
    // MAX_TOOL_ITERATIONS. The runtime must not emit an empty AgentMessageCompleted.
    const store = new InMemoryEventStore();
    const bus = new EventBus();
    const alwaysToolProvider = {
      generate: async () => ({ content: "", toolCalls: [{ id: "x", name: "loop", args: {} }] }),
      // eslint-disable-next-line require-yield
      generateStream: async function* () {
        yield { delta: "", toolCalls: [{ id: "x", name: "loop", args: {} }] };
      },
    };
    const runtime = new AgentRuntime({ provider: alwaysToolProvider, store, bus });
    const s = "s-exhaust";
    await seed(store, s);
    registerTool(
      toolSpecFromSchema("loop", "always called", z.object({})),
      async () => ({ ok: true }),
    );

    await runtime.runTurn(s);

    const events = await store.getEvents(s);
    const completions = events.filter(
      (e) => e.type === EventType.AGENT_MESSAGE_COMPLETED,
    );
    // Either zero completions, or none with empty content — never an empty phantom turn.
    expect(completions.every((e) => "content" in e && e.content !== "")).toBe(true);
  });
});
```

- [ ] **Step 2: Run, verify fail**
```bash
cd kaji/ts && bun run test tests/runtime.test.ts
```

- [ ] **Step 3: Create `cancellation.ts`**
```ts
/** Cancellation token for the agent loop, mirroring the Python CancellationToken. */
export class CancellationToken {
  private _cancelled = false;

  get isCancelled(): boolean {
    return this._cancelled;
  }

  cancel(): void {
    this._cancelled = true;
  }

  throwIfCancelled(): void {
    if (this._cancelled) {
      throw new Error("Agent run was cancelled");
    }
  }
}
```

- [ ] **Step 4: Create `context.ts`**
```ts
/**
 * Build the provider message list from replayed session state. Mirrors the
 * message construction in `kaji.runtime.agents.runtime`.
 */
import type { ProviderMessage } from "../providers/base";
import type { Message } from "../sessions/replay";

export function buildMessages(
  messages: Message[],
  systemPrompt?: string,
): ProviderMessage[] {
  const result: ProviderMessage[] = [];
  if (systemPrompt) {
    result.push({ role: "system", content: systemPrompt });
  }
  for (const m of messages) {
    if (m.role === "tool") {
      result.push({
        role: "tool",
        content: m.content,
        name: m.name,
        // H3: use the real tool_call_id threaded through replay (Task 7.5).
        // Fall back to the name only if an older event lacks it.
        tool_call_id: m.toolCallId ?? m.name ?? "unknown",
      });
    } else {
      result.push({ role: m.role, content: m.content });
    }
  }
  return result;
}
```

- [ ] **Step 5: Create `runtime.ts`** (ports `run_turn` from `runtime/agents/runtime.py:79`)
```ts
/**
 * Agent runtime: the ReAct tool-using loop, mirroring
 * `kaji.runtime.agents.runtime.AgentRuntime`.
 *
 * runTurn: replay state -> build messages -> stream from provider -> emit
 * events -> execute tool calls concurrently (scatter-gather) -> loop until the
 * provider returns no tool calls -> emit AgentMessageCompleted.
 */
import { EventBus } from "../events/bus";
import { KajiEvent, type KajiEventInput, EventType } from "../events/schemas";
import type { EventStore } from "../events/store";
import type { ModelProvider, ToolCall } from "../providers/base";
import { replaySession } from "../sessions/replay";
import { executeTool, listToolSpecs } from "../tools/registry";
import { CancellationToken } from "./cancellation";
import { buildMessages } from "./context";

const MAX_TOOL_ITERATIONS = 10;

export interface AgentRuntimeOptions {
  provider: ModelProvider;
  store: EventStore;
  bus: EventBus;
  systemPrompt?: string;
}

export interface RunTurnOptions {
  cancellationToken?: CancellationToken;
}

export class AgentRuntime {
  private readonly provider: ModelProvider;
  private readonly store: EventStore;
  private readonly bus: EventBus;
  private readonly systemPrompt?: string;

  constructor(options: AgentRuntimeOptions) {
    this.provider = options.provider;
    this.store = options.store;
    this.bus = options.bus;
    this.systemPrompt = options.systemPrompt;
  }

  async runTurn(sessionId: string, options: RunTurnOptions = {}): Promise<void> {
    const token = options.cancellationToken ?? new CancellationToken();
    token.throwIfCancelled();

    const emit = async (
      input: Omit<KajiEventInput, "session_id">,
    ): Promise<void> => {
      const event = KajiEvent.parse({ ...input, session_id: sessionId });
      await this.store.append(event);
      await this.bus.publish(event);
    };

    await emit({ type: EventType.AGENT_REASONING_STARTED });

    const tools = listToolSpecs();
    let finalContent = "";

    for (let i = 0; i < MAX_TOOL_ITERATIONS; i++) {
      token.throwIfCancelled();

      const events = await this.store.getEvents(sessionId);
      const state = replaySession(events);
      const messages = buildMessages(state.messages, this.systemPrompt);

      let content = "";
      const toolCalls: ToolCall[] = [];

      for await (const chunk of this.provider.generateStream(messages, tools)) {
        token.throwIfCancelled();
        if (chunk.delta) {
          content += chunk.delta;
          await emit({ type: EventType.AGENT_MESSAGE_DELTA, delta: chunk.delta });
        }
        toolCalls.push(...chunk.toolCalls);
      }

      if (toolCalls.length === 0) {
        finalContent = content;
        break;
      }

      // Announce all requests first (matches the Python planner's ordering).
      for (const tc of toolCalls) {
        await emit({
          type: EventType.TOOL_CALL_REQUESTED,
          tool_name: tc.name,
          tool_args: tc.args,
          tool_call_id: tc.id,
        });
      }

      // Scatter-gather: run concurrently, emit started/completed|failed per call.
      await Promise.all(
        toolCalls.map(async (tc) => {
          await emit({
            type: EventType.TOOL_CALL_STARTED,
            tool_name: tc.name,
            tool_call_id: tc.id,
          });
          try {
            const result = await executeTool("runtime", tc.name, tc.args);
            await emit({
              type: EventType.TOOL_CALL_COMPLETED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              result,
            });
          } catch (err) {
            await emit({
              type: EventType.TOOL_CALL_FAILED,
              tool_name: tc.name,
              tool_call_id: tc.id,
              error: err instanceof Error ? err.message : String(err),
            });
          }
        }),
      );
      // Loop: next iteration replays state including the new tool results.
    }

    // C1: only emit a completion when there is actual text. The Python reference
    // emits AgentMessageCompleted inside the loop guarded by truthy text and
    // nothing afterward; emitting an empty completion on max-iteration
    // exhaustion would inject a phantom assistant turn that replay then projects.
    if (finalContent) {
      await emit({ type: EventType.AGENT_MESSAGE_COMPLETED, content: finalContent });
    }
  }
}
```

> **Note on the test helper:** because the happy path always produces text (the mock returns `FINAL_TEXT`), `collectUntilCompleted` still terminates on `AGENT_MESSAGE_COMPLETED` for the normal cases. For the new max-iterations test (below), collect until `agent.reasoning.started` count or a fixed event budget instead of waiting for a completion that intentionally won't come.

- [ ] **Step 6: Run, verify pass**
```bash
cd kaji/ts && bun run test tests/runtime.test.ts
```
Expected: CancellationToken (2), buildMessages (3), AgentRuntime (4) all pass.

- [ ] **Step 7: Commit**
```bash
git add kaji/ts/src/runtime/ kaji/ts/tests/runtime.test.ts
git commit -m "feat(ts): add AgentRuntime ReAct loop, CancellationToken, buildMessages"
```

---

### Task 11: Export the provider + runtime surface

**Files:**
- Modify: `kaji/ts/src/index.ts`

- [ ] **Step 1: Append the new exports** (after the existing Tools block):
```ts
// Providers
export type {
  ModelProvider,
  ModelResponse,
  ModelResponseChunk,
  ProviderMessage,
  ToolCall,
} from "./providers/base";
export { MockProvider } from "./providers/mock";
export { clearProviders, getProvider, registerProvider } from "./providers/registry";

// Runtime
export {
  AgentRuntime,
  type AgentRuntimeOptions,
  type RunTurnOptions,
} from "./runtime/runtime";
export { CancellationToken } from "./runtime/cancellation";
export { buildMessages } from "./runtime/context";
```

- [ ] **Step 2: Full TS gate**
```bash
cd kaji/ts && bun run test && bun run typecheck && bun run build
```
Expected: all tests pass, no type errors, `dist/` built.

- [ ] **Step 3: Commit**
```bash
git add kaji/ts/src/index.ts
git commit -m "feat(ts): export provider and runtime surface from index"
```

---

### Task 12: Update ROADMAP

**Files:**
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Flip the statuses**
- Item 14 → `### 14. General document / knowledge RAG (DONE — retrieval capability; auto-injection into runtime deferred)`
- Item 16 → `### 16. Durable session persistence (DONE — SessionStore interface + InMemorySessionStore; durable backend deferred to serve)`
- Item 25 → `### 25. Provider layer (DONE)`
- Item 26 → `### 26. Agent runtime (DONE)`
- Item 27 → `### 27. Tool-loop glue (DONE)`
- Item 28 → `### 28. Reconcile sync vs async publish (DONE — publish stays async; runtime awaits it)`

- [ ] **Step 2: Commit**
```bash
git add docs/ROADMAP.md
git commit -m "docs: mark RAG, session persistence, and TS runtime items done"
```

---

### Task 13: README quickstarts (DX F1/F4/F5/F6 fix)

"Done on the roadmap, missing to every dev who tries it" is a launch blocker. Each of the three features needs a copy-paste-complete, zero-key-runnable snippet. All three use the infra-free path (stub embedder / `InMemorySessionStore` / `MockProvider`) so they run with no env, matching the existing agent quickstart's use of `mock`.

**Files:**
- Modify: `kaji/sdk/kaji/README.md` (Python: RAG + sessions)
- Modify: `kaji/ts/README.md` (TS: agent runtime)

- [ ] **Step 1: Add a "Document RAG" section to the Python README** with a runnable block using an injected stub embedder (no key needed), then one sentence naming the seam:
```python
import kaji

# Inject any embedder; this stub keeps the example key-free and runnable.
class StubEmbedder:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "cat" in text.lower() else [0.0, 1.0]

rag = kaji.DocumentRAG(embedder=StubEmbedder())
await rag.add_document(kaji.Document(id="d1", text="cats purr; dogs bark"))
chunks = await rag.retrieve("tell me about cats", top_k=1)
# For production, pass a real embedder (e.g. set GEMINI_API_KEY and use the default).
```
> Retrieval returns chunks; wiring them into the `AgentRuntime` prompt is your code today. Auto-injection is roadmap item 14 (deferred).

- [ ] **Step 2: Add a "Listing sessions" snippet** to the Python README:
```python
import kaji

store = kaji.InMemoryEventStore()
sessions = kaji.InMemorySessionStore()
mgr = kaji.SessionManager(store, session_store=sessions)

await mgr.record_session("s1", user_id="u1", title="First chat")
active = await mgr.list_active("u1")  # [{"session_id": "s1", ...}]
# Without a session_store, list_active returns [] (the SDK ships no durable index).
```

- [ ] **Step 3: Add a "Run an agent" quickstart to the TS README** (it currently has none) using `MockProvider`, and a note on the constructor difference from Python (DX F2):
```ts
import { AgentRuntime, EventBus, InMemoryEventStore, MockProvider, KajiEvent, EventType } from "@kaji/sdk";

const store = new InMemoryEventStore();
const bus = new EventBus();
const runtime = new AgentRuntime({ provider: new MockProvider(), store, bus });

await store.append(KajiEvent.parse({ type: EventType.SESSION_CREATED, session_id: "s1" }));
await store.append(KajiEvent.parse({ type: EventType.USER_MESSAGE, session_id: "s1", content: "hi" }));
await runtime.runTurn("s1");
```
> Note: the TS `AgentRuntime` takes an options object and runs the tool loop internally (no separate `ToolPlanner`); the Python `AgentRuntime` takes positional args plus a `ToolPlanner`. Same event sequence, different constructor ergonomics.

- [ ] **Step 4: Commit**
```bash
git add kaji/sdk/kaji/README.md kaji/ts/README.md
git commit -m "docs: add runnable quickstarts for RAG, sessions, and TS agent"
```

---

## Verification (run before declaring done)

- [ ] **Python SDK, infra-free import** (no env):
```bash
cd kaji/sdk && poetry run python -c "import kaji; print(kaji.DocumentRAG, kaji.InMemorySessionStore)"
```
- [ ] **Python full suite**:
```bash
cd kaji/sdk && poetry run pytest tests/ -q
```
Expected: all green (83 prior + ~25 new).
- [ ] **TS full gate**:
```bash
cd kaji/ts && bun run test && bun run typecheck && bun run build
```
Expected: all tests pass (existing + ~15 new), no type errors, clean build.
- [ ] **Both SDKs still infra-free**: neither import nor the happy-path run requires a DB, Redis, server, or API key (mock + in-memory only).

---

## Self-review

**Spec coverage:**

| spec item | covered by |
|-----------|-----------|
| RAG ingestion + chunking | Tasks 2 |
| RAG vector store + retrieval | Tasks 3, 4 |
| RAG infra-free + pluggable (Embedder reuse) | Task 4 (DocumentRAG defaults), D-A |
| RAG public surface | Task 5 |
| Durable session interface | Task 6 (SessionStore) |
| `list_active` real implementation | Task 7 |
| Session public surface | Task 7 step 5 |
| TS provider interface + registry + mock | Task 9 |
| TS AgentRuntime.runTurn (ReAct loop) | Task 10 |
| TS tool-loop glue (requested→started→completed/failed) | Task 10 runtime.ts |
| sync/async publish resolved | Task 8 (async, locked) |
| TS public surface | Task 11 |
| ROADMAP updated | Task 12 |

**Placeholder scan:** no TBDs, no "similar to Task N", every code block complete.

**Infra-free invariant:** every new default constructor (`DocumentRAG()`, `InMemoryVectorStore()`, `InMemorySessionStore()`, TS `MockProvider`, `AgentRuntime` with mock) touches no network/env. The Gemini embedder stays lazy (returns `[]` with no key), so `DocumentRAG()` with no key degrades to "stores/retrieves nothing" rather than raising.

**Type consistency (TS):** `ToolCall {id,name,args}` defined in `base.ts`, produced by `mock.ts`, consumed by `runtime.ts`. `ProviderMessage` defined in `base.ts`, built by `context.ts`. `ModelResponseChunk {delta,toolCalls}` yielded by mock, consumed by runtime. `AgentRuntimeOptions` defined + exported. Consistent.

**Cross-SDK parity:** TS event names match Python wire format (snake_case `tool_call_id`, `tool_name`, `tool_args`). Tool lifecycle order matches `ToolPlanner._execute_single`. `buildMessages` mirrors Python `ContextBuilder.build_messages` (system prompt prepend + tool message mapping).

---

## GSTACK REVIEW REPORT (/autoplan)

**STATUS: APPROVED 2026-06-07.** User kept original scope (RAG + persistence + TS runtime parity) over the CEO challenge to pivot to providers-first. All Eng (C1/H3/H4/M5) and DX (F1/F3/F4/F5/F6) auto-fixes folded into the task bodies. Ready to execute.

Reviewed 2026-06-07 on `feat/kaji-rag-persistence-ts-runtime`. Dual voices degraded to **[subagent-only]** (Codex CLI not authed). CEO + Eng + DX phases ran at full depth via independent Claude subagents.

### CEO consensus (subagent-only)
| Dimension | Subagent | Note |
|---|---|---|
| 1. Premises valid? | **DISAGREE** | "Adoptable" never defined; RAG-without-injection premise weak |
| 2. Right problem? | **DISAGREE** | Argues Anthropic provider + real TS provider + runnable quickstart beat all 4 items for adoption |
| 3. Scope calibration | DISAGREE | RAG is half a feature without injection; recommends cutting it this round |
| 4. Alternatives explored? | DISAGREE | TS-port existence and RAG-as-separate-package not analyzed |
| 5. Competitive risk | **DISAGREE (critical)** | No stated wedge vs LangChain/LlamaIndex/Vercel AI SDK/Mastra |
| 6. 6-month trajectory | DISAGREE | Two hand-maintained SDKs = 2x tax + drift; in-memory-only vector store = dead code or wall-hit |

→ This is a **USER CHALLENGE** (the model recommends changing the user's stated direction). Surfaced at the gate, NOT auto-decided.

### Eng consensus (subagent-only) — traced against real code
| # | Severity | Finding | Disposition |
|---|---|---|---|
| C1 | **critical** | TS runtime emits empty `AgentMessageCompleted` on max-iteration exhaustion; diverges from Python (which emits in-loop guarded by truthy text, nothing post-loop) | **AUTO-FIX** (Task 10) |
| H3 | **high** | `tool_call_id` derived from tool NAME discards the real id; breaks any real provider; the planned test *cements* the bug | **AUTO-FIX** (Tasks 10) |
| H4 | **high** | `cosine_similarity` silently truncates mismatched embedding dims via `zip` | **AUTO-FIX** (Tasks 1, 3) |
| M5 | medium | `record_session` is wired into the manager but NEVER called by any flow → `list_active` still always-empty in real runs; ROADMAP-16 "DONE" overclaims | **AUTO-FIX** (Task 7 wires it + Task 12 softens claim) |
| M6 | medium | `add_document` embeds chunks sequentially; slow for large docs | **DEFER** (matches existing retriever; note perf) |
| C2 | (verified non-issue) | loop terminates correctly; replay drops transient events | add regression test + replay comment |

Verified non-issues: empty-log replay can't fire (reasoning-started appended first); async `publish` decision (D-F) correct.

### DX consensus (subagent-only)
| # | Severity | Finding | Disposition |
|---|---|---|---|
| F1 | **critical** | Zero copy-paste examples / README updates for any of the 3 features | **AUTO-FIX** (new Task 13: README quickstarts) |
| F2 | high | Python (`positional + planner`) vs TS (`options, no planner`) `AgentRuntime` constructors diverge | **AUTO-FIX** (document in README; converge later) |
| F3 | high | `DocumentRAG()` with no key silently stores/retrieves nothing | **AUTO-FIX** (Task 4: warn-log on 0-chunks-from-nonempty) |
| F4 | high | RAG↔runtime boundary undocumented; devs expect auto-wiring | **AUTO-FIX** (README sentence naming the seam) |
| F5/F6 | medium | Pluggability invisible; "usable RAG" quietly needs a key | **AUTO-FIX** (README uses stub embedder, no key) |

DX ratings post-ship: ingest+retrieve **4/10**, list sessions **6/10**, run TS agent **7/10**.

### Cross-phase theme (high-confidence signal)
**"Half-feature / overclaim" recurs in CEO #6, Eng M5, and DX F4** — the plan ships capabilities (RAG retrieval, `list_active`) that aren't wired into a working end-to-end path, then marks them DONE. Three independent reviewers flagged the same gap. Disposition: tighten ROADMAP wording to "capability shipped, wiring deferred" AND wire `record_session` so persistence is genuinely exercised.

### Decision Audit Trail
| # | Phase | Decision | Class | Principle | Rationale |
|---|-------|----------|-------|-----------|-----------|
| 1 | Eng | Fix C1: guard final emit `if (finalContent)`, mirror Python | Mechanical | P5 explicit | Reference divergence + silent empty turn; clearly right |
| 2 | Eng | Fix H3: thread real `tool_call_id` through Message→replay→buildMessages | Mechanical | P1 completeness | Latent break for real providers; freezing the wrong data model now is expensive |
| 3 | Eng | Fix H4: dimension guard in `InMemoryVectorStore.search` | Mechanical | P1 completeness | Silent correctness bug; cheap guard |
| 4 | Eng+DX | Fix M5: wire `record_session` into runtime + soften ROADMAP-16 | Mechanical | P5 explicit | Avoid overclaiming DONE; make persistence real |
| 5 | DX | Add Task 13: README quickstarts for all 3 features, stub-embedder (no key) | Mechanical | P1 completeness | "Done on roadmap, missing to devs" is a launch blocker |
| 6 | DX | Fix F3: warn-log when add_document stores 0 from non-empty text | Mechanical | P5 explicit | Silent footgun → actionable problem+cause+fix |
| 7 | Eng | Defer M6 (sequential embedding) | Mechanical | P3 pragmatic | Matches existing retriever; note perf, not a blocker |
| 8 | CEO | Scope/priority of whole plan (RAG vs Anthropic provider; TS-port existence) | **USER CHALLENGE** | — | Models lack adoption context; user decides at gate |

All Eng/DX auto-fixes are folded into the task bodies below the report. The CEO User Challenge is the gate question.
