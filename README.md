# AgentKit

AgentKit decouples conversational latency from heavy task execution. Audio
streams in over a WebSocket, speech-to-text drives an LLM reasoning loop, and
responses stream back as text (and, soon, synthesized speech) — while tool
calls run asynchronously on a separate worker so the conversation never blocks.

> **Status:** pre-release / active development. The full STT → LLM → TTS path
> is wired; barge-in and durable persistence are in progress.

## Repository layout

The `agentkit` SDK is the root project; the client apps live under `apps/` and
are managed as a [Bun](https://bun.sh) + [Turborepo](https://turborepo.com)
workspace. Each unit owns its own README.

| Path | What it is | Stack |
| ------------------------------ | ------------------------------------------------------------------------- | ----------------------------------- |
| [`agentkit/`](agentkit) | The `agentkit` backend SDK — voice-agent runtime, FastAPI server, workers (this is the root Python project) | Python 3.11, FastAPI, TaskIQ, Redis |
| [`apps/web`](apps/web) | Web client | React 19, Vite |
| [`apps/desktop`](apps/desktop) | Native desktop client | Tauri 2, React 19, Vite |

The Python SDK is the heart of the project; the apps are clients that talk to
its API. See [`agentkit/README.md`](agentkit/README.md) for the SDK
architecture in depth.

## How the pieces fit together

A client streams microphone audio to the SDK's API over a WebSocket. The API
relays it to a speech-to-text provider, publishes transcripts onto a Redis
stream, and a worker runs the LLM reasoning loop — streaming responses back to
the client and dispatching tool calls to a separate task queue.

```
        ┌───────────────────────────────┐
        │    Clients (web / desktop)    │
        └───────────────┬───────────────┘
                        │ WebSocket (audio ⇄ text)
                        ▼
        ┌───────────────────────────────┐
        │       SDK API (FastAPI)       │
        │    REST routes + STT socket   │
        └───────────────┬───────────────┘
                        │ Redis Streams / Pub-Sub
            ┌───────────┴────────────┐
            ▼                        ▼
   ┌──────────────────┐    ┌──────────────────┐
   │    bus-worker    │    │      worker      │
   │  LLM reasoning   │◀──▶│  async tool exec │
   │ loop + event bus │    │     (TaskIQ)     │
   └────────┬─────────┘    └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │ Postgres + Redis │
   └──────────────────┘
```

Three processes — `api`, `bus-worker`, and `worker` — communicate over Redis
so that slow tool execution never stalls the real-time conversation. The
[SDK README](agentkit/README.md) breaks down each process and the event flow.

## Getting started (development)

**Prerequisites:** [Bun](https://bun.sh) ≥ 1.3 and Node ≥ 22 (for the clients);
Python 3.11+ and [Poetry](https://python-poetry.org/) (for the SDK); Docker
(for Postgres + Redis).

```bash
# Install all JS/TS workspace dependencies from the repo root
bun install

# Run a client (Turborepo filters by workspace)
bun --filter @agentkit/desktop dev
bun --filter web dev

# The Python SDK has its own toolchain (run from the repo root) — see its README
poetry install && poetry run pytest
```

Per-app setup lives in each app's README; the SDK's lives in
[`agentkit/README.md`](agentkit/README.md). For full backend configuration, see
the [Setup Guide](docs/SETUP.md).

## Repository conventions

- **JS/TS** is managed by Bun workspaces + Turborepo; lint and format via
  [oxlint](https://oxc.rs) / oxfmt (`bun run lint`, `bun run format`).
- **Python** (the SDK) is managed independently by Poetry from the repo root;
  it is not part of the Bun workspace.
- Generated artifacts (`__pycache__/`, `*.pyc`, `logs/`, build output) stay out
  of the repo.
- Client apps go under `apps/*`. The SDK is the root project.