This document is written for **LLMs and human contributors** working on the Python backend. It explains how the API is structured, how data flows through the system, and how new features must be implemented safely and correctly.

If a task is clear but the implementation details are uncertain, **default to official documentation** (FastAPI, Redis Streams, Taskiq, Supabase, Cartesia, Gemini). If unsure, explicitly request the relevant docs instead of guessing.

---

## 1. Core Principles

### 1.1 Python & Tooling

* Python **3.13+**
* Use **type hints everywhere**
* Enforce correctness with **ty** (no unresolved types, no `Any` leaks)
* Prefer explicit imports and clear module boundaries

### 1.2 Async-First Design

* All I/O is async
* No blocking calls in request handlers or workers
* Use `asyncio.TaskGroup` where fan-out is required

### 1.3 Error Handling

* Never swallow exceptions
* Define domain-specific error types
* Log structured errors with context (request id, user id, conversation id)
* Fail fast on schema or contract violations

### 1.4 Code Size & Reuse

* Keep files under **400–500 LOC**
* Shared logic must live in `app/core` or `app/services`
* Avoid circular imports

---

## 2. High-Level Architecture

```
Client (iOS)
  ↓ WebSocket / HTTP
FastAPI Routers
  ↓
Services (LLM, STT, TTS, Integrations)
  ↓
Redis Streams / Taskiq Workers
  ↓
Supabase (Postgres + Vector)
```

The API is both:

* A **real-time streaming system** (audio, tokens)
* A **task-based pipeline** (tools, embeddings, integrations)

---

## 3. Directory Responsibilities

### `/alembic`

Database migrations only.

* No business logic
* Migrations must be reversible

---

### `/app/core`

**Infrastructure primitives**

* `config.py` — environment config (staging vs production)
* `database.py` — async Supabase/Postgres access
* `redis.py` — Redis + Streams client
* `broker.py` — Taskiq broker setup
* `logging.py` — structured logging
* `events.py` — cross-service event definitions

No domain logic here.

---

### `/app/models`

**Database models**

* Mirrors Supabase schema exactly
* No business logic
* Typed fields only

Examples:

* `conversation.py`
* `message.py`
* `vector_embedding.py`

---

### `/app/schemas`

**Request / response contracts**

* FastAPI boundary only
* Pydantic v2 models
* Strict validation

If validation fails, return explicit 4xx errors.

---

### `/app/routers`

**HTTP & WebSocket entry points**

* Thin layers
* No heavy logic
* Delegate immediately to services

Important routers:

* `stt.py` — audio websocket
* `gemini.py` — LLM interaction
* `tools.py` — tool execution

---

### `/app/services`

**All business logic lives here**

Subdomains:

* `pipeline/` — voice + LLM flow
* `integrations/` — third-party APIs
* `spotify/` — playback control
* `workspace/` — Gmail, Calendar, Tasks

Services must be:

* Stateless where possible
* Fully typed
* Independently testable

---

### `/app/workers`

**Taskiq workers**

* Long-running background tasks
* No HTTP concerns
* Must be idempotent

---

## 4. Core Pipeline & TTS

### 4.1 Cartesia Integration

Create:

```
app/services/pipeline/cartesia.py
```

Responsibilities:

* Maintain Cartesia WebSocket connection
* Stream text chunks as they arrive
* Emit PCM audio frames

Rules:

* No buffering entire responses
* Handle reconnects explicitly
* Backpressure-aware

---

### 4.2 LLM Worker (`llm_worker.py`)

Responsibilities:

* Consume user utterances
* Fetch conversation history from **Supabase** (not Redis)
* Stream tokens from Gemini

Routing logic:

* Text chunks → Cartesia (TTS)
* Tool calls → Redis Streams / Taskiq

No audio or WebSocket code here.

---

### 4.3 WebSocket Forwarding (`stt.py`)

Responsibilities:

* Accept client audio frames
* Forward binary PCM frames from Redis to client WebSocket

Rules:

* Binary passthrough only
* No transcoding here
* Enforce PCM S16LE, 16kHz

---

## 5. Spotify Service Integration

### Queue Management

* Always prefer queue-based playback
* Never rely solely on "play next" APIs
* Detect stalled playback and recover

### Command Parsing

* Support:

  * play song
  * play album
  * play playlist
* Normalize commands before execution

### Cold Start

* If no active device playback:

  * Select device
  * Start playback explicitly

All Spotify logic must be unit-tested with mocked responses.

---

## 6. Memory & Context

### Model Updates

* Use `gemini-3.0-flash`
* Model name must be centralized

### Conversation History

* Fetch from Supabase
* Ordered, bounded context window

### Background Embeddings

Create a new Taskiq worker:

* Triggered on conversation completion
* Generate embeddings using `text-embedding-3-small`
* Upsert into `vector_embeddings`

Worker must be:

* Retry-safe
* Idempotent

---

## 7. Configuration

### Audio Format (Hard Requirement)

* PCM S16LE
* 16kHz sample rate

Reject any mismatched format at ingress.

---

## 8. Redis & Taskiq Usage

### Redis Streams

* Used for:

  * Audio frames
  * Tool execution events

Messages must be:

* Versioned
* Schema-validated

### Taskiq

* Long-running or blocking work only
* No network calls in FastAPI handlers that can be deferred

---

## 9. Testing Expectations

### Unit Tests

* Service-level logic
* Spotify edge cases
* Command parsing

### Integration Tests

* Redis stream flow
* Taskiq worker execution

### Load & Latency

* Token streaming under load
* Audio frame forwarding

---

## 10. LLM Operating Instructions

When modifying or adding backend code:

1. Do not invent APIs
2. Enforce types with ty
3. Keep async boundaries clear
4. Centralize shared logic
5. Ask for docs if uncertain

This document is the source of truth for backend implementation.
