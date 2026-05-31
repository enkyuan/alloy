# AgentKit

Build agentic voice platforms in Python.

AgentKit is a library for composing real-time voice agents: streaming STT, LLM
orchestration, streaming TTS, tool calling, sessions, and event-sourced replay.

## Status

Pre-release. The STT side of the pipeline is wired (Soniox), Gemini is the
default LLM, and TTS / VAD / barge-in are in progress.

## Install

```bash
pip install agentkit
```

## Quickstart

```python
# coming soon
```

## Architecture

AgentKit runs as three processes communicating over Redis, which keeps
conversational latency decoupled from heavy tool execution:

- **`api`** — FastAPI app; serves REST routes and the STT WebSocket.
- **`bus-worker`** — the reasoning loop. Consumes transcription events, calls
  the LLM, and emits `AgentResponse` / `ToolCall` events on an internal bus.
- **`worker`** — TaskIQ workers that execute tool calls and publish results.

The voice path is **STT → LLM → TTS**: audio streams in over WebSocket to
Soniox (STT), transcripts drive the LLM (Gemini by default), and responses are
synthesized back to the caller (TTS — in progress). Events flow over Redis
Streams (durable hand-off) and Pub/Sub (real-time fan-out to the client).

## Development

**Prerequisites:** Python 3.11+, [Poetry](https://python-poetry.org/), Docker.

```bash
# 1. Install dependencies (creates the venv and installs agentkit editable)
poetry install

# 2. Start test dependencies (Postgres with pgvector; Redis is faked in tests)
docker compose -f ../../docker/docker-compose.yml up -d db

# 3. Run the tests
poetry run pytest
```

Tests collect with no environment configuration — `tests/conftest.py` supplies
safe defaults for `DATABASE_URL`, `SUPABASE_ANON_KEY`, and `JWT_SECRET`. The
~12 database-backed tests need the Postgres service from step 2; the rest are
pure unit tests and pass without it. Coverage is reported on every run; CI
enforces a floor (see `.github/workflows/sdk-tests.yml`).
