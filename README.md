# AgentKit

AgentKit is an embeddable SDK for building agentic platforms in Python: an agent
runtime, tool generation, retrieval, and pluggable LLM providers, for both text
and voice. The core is dependency-injected and infra-free. `pip install
agentkit`, import the building blocks you need, and compose them into your own
product.

The repo also ships a reference application built on the SDK: a real-time voice
service (FastAPI, Redis, Postgres, behind the optional `server` extra) plus web
and desktop clients.

> **Status:** pre-release. The core SDK is usable today; the reference voice
> service wires the STT → LLM → TTS path (barge-in and durable persistence are in
> progress).

## Repository layout

All distributions live under `packages/`; the platform demos under `demos/` are
managed as a [Bun](https://bun.sh) + [Turborepo](https://turborepo.com)
workspace. Each unit owns its own README.

| Path | What it is | Stack |
| ---------------------------------- | ------------------------------------------------------------------------- | ----------------------------------- |
| [`packages/sdk`](packages/sdk) | The `agentkit` SDK: agent runtime, toolgen, providers, text/voice modalities | Python 3.11 |
| [`packages/serve`](packages/serve) | `agentkit-serve` — reference FastAPI server + workers (path-depends on the SDK) | Python 3.11, FastAPI, TaskIQ, Redis |
| [`packages/ts`](packages/ts) | `@agentkit/sdk` — the TypeScript SDK | TypeScript |
| [`demos/web`](demos/web) | Web usage demo | React 19, Vite |
| [`demos/desktop`](demos/desktop) | Desktop usage demo | Tauri 2, React 19, Vite |

The Python SDK is the heart of the project; `serve` deploys it as a service and
the demos show how to consume it on each platform. See
[`packages/sdk/agentkit/README.md`](packages/sdk/agentkit/README.md) for the SDK
and its architecture in depth.

## How the pieces fit together

You embed the SDK in your own app, where an agent runtime drives an LLM over a
typed event bus, generates and executes tools (concurrently, scatter-gather),
and exchanges messages through whichever modality you wire up. The web and
desktop demos here show how to connect to it on each platform.

```
                                                    ┌────────────────────────────┐
   ┌─────────────────────────┐                      │ your app  (embeds the SDK) │
   │ demo clients            │                      │                            │
   │ web · desktop · your UI │  ◀── text/audio ──▶  │ agent runtime + event bus  │
   └─────────────────────────┘                      │ toolgen · providers · RAG  │
                                                    └────────────────────────────┘
                                                                  │ ToolCall / ToolResult
                                                                  ▼
                                                    ┌────────────────────────────┐
                                                    │ tools  (async, concurrent) │
                                                    └────────────────────────────┘
```

The reference `server` extra runs that runtime as FastAPI, Redis, and Postgres
processes (`api`, `bus-worker`, `worker`) so heavy tool execution never stalls a
real-time exchange; a voice client adds STT/TTS at the edge. The
[SDK README](packages/sdk/agentkit/README.md) breaks down each process and the event flow.

## Getting started

**Prerequisites:** [Bun](https://bun.sh) ≥ 1.3 and Node ≥ 22 (for the demos);
Python 3.11+ and [Poetry](https://python-poetry.org/) (for the SDK); Docker
(for Postgres + Redis).

```bash
# Install all JS/TS workspace dependencies from the repo root
bun install

# Run a demo (Turborepo filters by workspace)
bun --filter @agentkit/desktop dev
bun --filter web dev

# The Python SDK has its own Poetry toolchain; see its README
cd packages/sdk && poetry install && poetry run pytest
```

Per-demo setup lives in each demo's README; the SDK's lives in
[`packages/sdk/agentkit/README.md`](packages/sdk/agentkit/README.md). For full
backend configuration, see the [Setup Guide](docs/SETUP.md).

## Conventions

- **JS/TS** is managed by Bun workspaces + Turborepo; lint and format via
  [oxlint](https://oxc.rs) / oxfmt (`bun run lint`, `bun run format`).
- **Python** (`packages/sdk`, `packages/serve`) is managed independently by
  Poetry; it is not part of the Bun workspace.
- Generated artifacts (`__pycache__/`, `*.pyc`, `logs/`, build output) stay out
  of the repo.
- Platform demos go under `demos/*`. The SDK is the root project.