# AgentKit

Build real-time, agentic voice agents in Python.

`agentkit` is the backend SDK and runtime for the AgentKit project: streaming
speech-to-text, an LLM reasoning loop with tool calling, an event-sourced
message bus, sessions, and streaming text-to-speech. It is designed so that
conversational latency is decoupled from heavy tool execution.

> **Status:** pre-release / active development. The full STT → LLM → TTS path
> is wired (Soniox STT, Gemini default LLM, Gemini/OpenAI TTS). Barge-in and
> durable persistence are still in progress.

## Install

```bash
pip install agentkit
```

## Quick start

```python
# coming soon — the public composition API is being finalized.
# For now, run the server + workers locally (see "Development" below) and
# stream audio to the STT WebSocket at /api/v1/stt.
```

## Architecture

AgentKit runs as **three processes** that communicate over Redis. Splitting
the real-time conversation loop from asynchronous tool execution is the core
design decision: a slow tool call can never stall speech in or out.

| Process | Responsibility |
| ------------- | ---------------------------------------------------------------- |
| `api` | FastAPI app — REST routes and the STT WebSocket endpoint |
| `bus-worker` | The reasoning loop: consumes transcripts, calls the LLM, runs the event bus, emits responses and tool calls |
| `worker` | TaskIQ workers that execute tool calls asynchronously and publish results |

### Data flow

The voice path is **STT → LLM → TTS**. Audio enters over a WebSocket; the LLM
drives the response; tool calls fan out to the worker and their results flow
back into the reasoning loop.

```
   ┌─────────────────┐
   │     client      │   audio in / text out
   └────────┬────────┘
            │  WebSocket
            ▼
   ┌─────────────────┐
   │  api (FastAPI)  │   STT WebSocket + REST
   └────────┬────────┘
            │  transcript          (Redis Stream)
            ▼
   ┌─────────────────┐
   │    bus-worker   │   LLM reasoning loop + event bus
   │   (reasoning)   │
   └────────┬────────┘
            │  ToolCall            (TaskIQ queue)
            ▼
   ┌─────────────────┐
   │      worker     │   async tool execution
   │   (tool exec)   │
   └─────────────────┘
```

Two paths close the loop (omitted above for clarity):

- **`bus-worker` → client**: each `AgentResponse` is published on Redis
  **Pub/Sub** and streamed to the connected client in real time. When a TTS
  provider is configured (`TTS_PROVIDER`), the response is also synthesized and
  streamed as ordered `AgentAudioChunk` events alongside the text.
- **`worker` → `bus-worker`**: each tool result is written back to a Redis
  **Stream**, re-entering the reasoning loop so the LLM can continue.

Two Redis mechanisms are used deliberately:

- **Streams** for durable, at-least-once hand-off between processes
  (transcripts in, tool results back) with consumer groups and dead-letter
  queues.
- **Pub/Sub** for real-time, fire-and-forget fan-out of agent responses to the
  connected client.

The reasoning loop uses **scatter-gather** for tools: when the LLM requests
multiple tool calls, they are dispatched concurrently and the loop resumes once
results return (bounded by a max round-trip count).

### Module layout

The package is organized in layers, from foundational to orchestration. Lower
layers do not import upper layers.

```
agentkit/
├── core/          # foundation: config, redis, db, http, auth, errors
├── types/         # shared type definitions
├── events/        # event envelopes, store, replay
├── observability/ # tracing, metrics, timeline
├── providers/     # LLM providers (gemini, kimi, mock) + errors
├── tools/         # tool registry, execution, policies, idempotency
├── sessions/      # session state + websocket lifecycle
├── voice/         # STT (soniox), TTS (gemini/openai), audio — a modality
│   ├── stt/
│   └── tts/
├── text/          # text modality
├── agents/        # the agent runtime (NOT voice-specific)
│   ├── messaging/ #   typed event bus: Bus, Bridge, RouteBuilder
│   └── nodes/     #   reasoning nodes: ReasoningNode, AgentReasoningNode
├── workflows/     # idempotency + queue helpers
├── workers/       # process entrypoints + TaskIQ tasks
└── server/        # FastAPI app + versioned routes (v1)
```

A note on naming: `agents/messaging` and `agents/nodes` are the **generic**
agent runtime — the event bus and reasoning loop are not tied to voice. Voice
is one modality (`voice/`) that plugs into them.

### Providers and modalities are pluggable

- **LLM providers** implement a common interface in `providers/` (Gemini,
  Kimi/OpenRouter, and a mock for tests). Selected via `AGENTKIT_MODEL_PROVIDER`.
- **TTS providers** implement the `TTSProvider` protocol in `voice/tts/` and
  are selected via `TTS_PROVIDER` (`none` by default; `gemini` available). A
  factory returns a no-op adapter when TTS is unconfigured, so text-only
  operation always works.

## Configuration

Settings load from environment variables (or a `.env` file) via
`agentkit.core.config.Settings`. The essentials:

| Variable | Required | Purpose |
| -------------------------- | -------- | ----------------------------------- |
| `DATABASE_URL` | yes | Postgres connection (asyncpg) |
| `SUPABASE_ANON_KEY` | yes | Supabase auth |
| `JWT_SECRET` | yes | Token signing / encryption fallback |
| `REDIS_URL` | no | Defaults to `redis://redis:6379/0` |
| `SONIOX_API_KEY` | no | Enables real-time STT |
| `AGENTKIT_MODEL_PROVIDER` | no | LLM provider (default `kimi`) |
| `GEMINI_API_KEY` | no | Gemini LLM + TTS |
| `OPENAI_API_KEY` | no | OpenAI TTS |
| `TTS_PROVIDER` | no | `none` (default), `gemini`, or `openai` |

See [`.env.example`](.env.example) for the full list.

## Development

**Prerequisites:** Python 3.11+, [Poetry](https://python-poetry.org/), Docker.

```bash
# 1. Install dependencies (creates the venv and installs agentkit editable)
poetry install

# 2. Start test dependencies (Postgres with pgvector; Redis is faked in tests)
docker compose -f ../docker/docker-compose.yml up -d db

# 3. Run the tests
poetry run pytest
```

Tests collect with no environment configuration — `tests/conftest.py` supplies
safe defaults for `DATABASE_URL`, `SUPABASE_ANON_KEY`, and `JWT_SECRET`. The
database-backed tests need the Postgres service from step 2; the rest are pure
unit tests and pass without it. Coverage is reported on every run; CI enforces
a floor (see [`.github/workflows/sdk-tests.yml`](../.github/workflows/sdk-tests.yml)).

## Project layout notes

The SDK is intentionally a **single package** for now. The module layout above
already reflects the intended layering, and several layers (`core`, `events`,
`voice`) could be extracted into standalone packages later. That split is
deferred until there is a second consumer, because three dependency cycles
(`agents ⇄ tools`, `agents ⇄ workers`, `workers ⇄ workflows`) would first need
to be broken — they are harmless within one package but cannot cross package
boundaries.