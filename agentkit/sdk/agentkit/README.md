# AgentKit

`agentkit` is an embeddable SDK for building agents into your own platform:
import the pieces you need and compose them. The core is dependency-injected and
infra-free (no database, Supabase, or web server). A reference service (FastAPI,
Redis, Postgres) ships behind the optional `server` extra, structured so heavy
tool execution never stalls a real-time exchange.

> **Status:** pre-release. The core SDK (runtime, toolgen, providers,
> text/voice) is usable today. The reference voice service wires the STT → LLM →
> TTS path (Soniox STT, Gemini LLM, Gemini/OpenAI TTS); barge-in and durable
> persistence are in progress.

## Install

```bash
pip install agentkit         # core SDK, embed in your own app
pip install agentkit-serve   # the reference service (FastAPI + workers); pulls in agentkit
```

## Quick start

`import agentkit` works with no environment configured. Compose the building
blocks yourself:

```python
import agentkit

# Event-sourced building blocks, all in-memory by default (no infra required):
store = agentkit.InMemoryEventStore()
bus = agentkit.InMemoryEventBus()
sessions = agentkit.SessionManager(store)

# Toolgen: register your own tools. Schemas can be generated from Pydantic models.
from pydantic import BaseModel

class GetWeather(BaseModel):
    city: str

@agentkit.register_tool(
    agentkit.tool_spec_from_model("get_weather", "Look up weather", GetWeather)
)
async def get_weather(ctx: agentkit.ToolContext, args: dict) -> dict:
    return {"city": args["city"], "tempF": 68}

# Tools execute without a database by default; ctx.db is None unless you inject one.
result = await agentkit.execute_tool("user-1", "get_weather", {"city": "Seattle"})
```

### Run an agent

`AgentRuntime` is the provider-agnostic ReAct loop: it projects session state
from the event log, calls a `ModelProvider`, and executes tool calls
scatter-gather, looping until the model is done. It needs no infra — the built-in
`mock` provider runs the whole loop with no API key, which is the zero-setup way
to see it work (swap in `get_provider("kimi")` or another provider for real
generations).

```python
import agentkit

store = agentkit.InMemoryEventStore()
bus = agentkit.InMemoryEventBus()

# A tool the agent can call. (The built-in mock provider calls tools with empty
# arguments, so give it one that needs none to see the loop run cleanly.)
@agentkit.register_tool(
    agentkit.ToolSpec(
        name="server_time",
        description="Return the current server time.",
        parameters={"type": "object", "properties": {}, "required": []},
    )
)
async def server_time(ctx: agentkit.ToolContext, args: dict) -> dict:
    import time
    return {"epoch": time.time()}

# The planner runs tool calls the model requests; wire it to execute_tool so the
# tools you registered are reachable.
planner = agentkit.ToolPlanner(
    executor=lambda name, args: agentkit.execute_tool("user-1", name, args)
)

runtime = agentkit.AgentRuntime(
    bus=bus,
    store=store,
    provider=agentkit.get_provider("mock"),
    planner=planner,
    tools=agentkit.list_tool_specs(),  # surface registered tools to the model
)

# Seed a user turn, then run the loop. Emitted events land in the store: the
# mock requests the tool, the planner runs it, and the loop finishes.
await store.append(agentkit.UserMessage(session_id="s1", content="What time is it?"))
await runtime.run_turn("s1")

state = await store.get_events("s1")  # AgentMessageDelta/Completed, ToolCall* events
```

> The `mock` provider runs the whole loop with no API key — ideal for a first
> run and for tests. Swap in `get_provider("kimi")` (or another provider, with
> its key set) for real generations.

For the full real-time voice service (STT → LLM → TTS over Redis), install the
`server` extra and use the process layout below.

## Reference service architecture

The sections below describe the reference service the SDK ships with: one way to
deploy the runtime, not a requirement for using it. It runs as three processes
over Redis, so a slow tool call can never stall a real-time exchange.

| Process | Responsibility |
| ------------- | ---------------------------------------------------------------- |
| `api` | FastAPI app: REST routes and the (voice) STT WebSocket endpoint |
| `bus-worker` | The reasoning loop: consumes input, calls the LLM, runs the event bus, emits responses and tool calls |
| `worker` | TaskIQ workers that execute tool calls asynchronously and publish results |

### Data flow

The voice path is STT → LLM → TTS: audio enters over a WebSocket, the LLM drives
the response, and tool calls fan out to the worker and back. A text
configuration uses the same loop without the STT/TTS edges.

```
   ┌────────────────────────────────┐
   │             client             │
   └────────┬──────────────┴────────┘
            ▼              │            in: text / audio          out: text / audio
   ┌────────────────────────────────┐
   │         api (FastAPI)          │   REST + STT/TTS WebSocket (voice)
   └────────┬──────────────┴────────┘
            ▼              │            in: message (Redis Stream)   out: response (Pub/Sub)
   ┌────────────────────────────────┐
   │     bus-worker (reasoning)     │   LLM loop + event bus
   └────────┬──────────────┴────────┘
            ▼              │            out: ToolCall (TaskIQ)    in: ToolResult (Redis Stream)
   ┌────────────────────────────────┐
   │       worker (tool exec)       │   async tools, scatter-gather
   └────────────────────────────────┘
```

Everything below the `api` row is modality-agnostic. Two paths close the loop
(the up-arrows above):

- **`bus-worker` → client**: each `AgentResponse` is published on Redis Pub/Sub
  and streamed to the client. With a TTS provider configured (`TTS_PROVIDER`),
  the response is also synthesized and streamed as ordered `AgentAudioChunk`
  events alongside the text.
- **`worker` → `bus-worker`**: each tool result is written back to a Redis
  Stream, re-entering the reasoning loop so the LLM can continue.

The two Redis mechanisms are deliberate: Streams for durable, at-least-once
hand-off between processes (consumer groups, dead-letter queues); Pub/Sub for
fire-and-forget fan-out to the client. Tools run scatter-gather: multiple tool
calls dispatch concurrently and the loop resumes once results return, bounded by
a max round-trip count.

### Module layout

The package is organized in layers, from foundational to orchestration. Lower
layers do not import upper layers.

```
agentkit/
├── core/             # foundation: config, redis, db, http, auth, errors
├── types/            # shared type definitions
├── infra/            # backbone above core
│   ├── events/       #   event envelopes, store, replay
│   ├── realtime/     #   redis stream/pub-sub helpers (history, outbox, DLQ)
│   └── observability/#   tracing, metrics, timeline
├── modalities/       # input/output channels that plug into the runtime
│   ├── voice/        #   STT (soniox), TTS (gemini/openai), audio
│   │   ├── stt/
│   │   └── tts/
│   └── text/         #   text modality
└── runtime/          # the agent reasoning/orchestration engine
    ├── agents/       #   reasoning loop (NOT voice-specific)
    │   ├── messaging/#     typed event bus: Bus, Bridge, RouteBuilder
    │   └── nodes/    #     reasoning nodes: ReasoningNode, AgentReasoningNode
    ├── providers/    #   LLM providers (gemini, kimi, openai, mock) + errors
    ├── tools/        #   tool registry, execution, retrieval, policies
    ├── sessions/     #   session state + websocket lifecycle
    └── workflows/    #   idempotency + queue helpers
```

The FastAPI server and TaskIQ workers are **not** in the SDK — they live in the
separate [`agentkit-serve`](../../serve/README.md) distribution.

`infra`, `modalities`, and `runtime` are organizational groupings; `core` and
`types` stay at the root because nearly everything depends on them.
`runtime/agents/` (the event bus and reasoning loop) is generic, not tied to
voice. Voice is one modality under `modalities/voice/` that plugs into it.

### Providers and modalities are pluggable

- **LLM providers** implement a common interface in `runtime/providers/`
  (Gemini, Kimi/OpenRouter, OpenAI, plus a keyless `mock`). Selected via
  `AGENTKIT_MODEL_PROVIDER` (default `kimi`). Tools are passed to providers in a
  neutral `[{name, description, parameters}]` format; each provider translates it
  to its own function-calling shape, so a tool works across providers unchanged.
- **TTS providers** implement the `TTSProvider` protocol in
  `modalities/voice/tts/` and are selected via `TTS_PROVIDER` (`none` by
  default; `gemini` and `openai` available). A factory returns a no-op adapter
  when TTS is unconfigured, so text-only operation always works.

## Configuration

Settings load lazily from environment variables (or a `.env` file) via
`agentkit.core.config.get_settings()`, constructed only when a component that
needs them is used. No configuration is needed to `import agentkit`. The
variables below apply to the server stack (`server` extra); the core SDK needs
none of them.

| Variable | Required | Purpose |
| -------------------------- | --------------- | ----------------------------------- |
| `DATABASE_URL` | server only | Postgres connection (asyncpg) |
| `SUPABASE_ANON_KEY` | server only | Supabase auth |
| `JWT_SECRET` | server only | Token signing / encryption fallback |
| `REDIS_URL` | for the bus/workers | Defaults to `redis://redis:6379/0` |
| `SONIOX_API_KEY` | no | Enables real-time STT |
| `AGENTKIT_MODEL_PROVIDER` | no | LLM provider: `kimi` (default), `gemini`, `openai`, `mock` |
| `GEMINI_API_KEY` | no | Gemini LLM + TTS |
| `OPENAI_API_KEY` | no | OpenAI LLM + TTS |
| `OPENAI_MODEL` | no | OpenAI model (default `gpt-4o`) |
| `TTS_PROVIDER` | no | `none` (default), `gemini`, or `openai` |

See [`.env.example`](.env.example) for the full list.

## Development

**Prerequisites:** Python 3.11+, [Poetry](https://python-poetry.org/), Docker.

The SDK (`agentkit/sdk`) and the reference service (`agentkit/serve`) are
separate Poetry distributions.

```bash
# Core SDK: install + test (no database, no server deps required).
cd agentkit/sdk
poetry install
poetry run pytest tests/  # the SDK test suite, runs with no env configured

# Reference service: install (pulls in the SDK via a path dependency) + test.
cd agentkit/serve
poetry install
docker compose -f ../../docker/docker-compose.yml up -d db  # Postgres for DB tests
poetry run pytest tests/
```

The SDK tests need no environment (the building blocks are infra-free). The
service tests under `agentkit/serve/tests/` cover the API and workers; the
database-backed ones need the Postgres service. CI runs the two suites as
separate jobs (see [`.github/workflows/sdk-tests.yml`](../.github/workflows/sdk-tests.yml)).

## Project layout notes

The repo ships **two distributions**: `agentkit` (this SDK) and
[`agentkit-serve`](../../serve/README.md) (the reference FastAPI + workers
service, which path-depends on the SDK). The SDK has no dependency on the
service — the boundary mirrors langchain / langserve.

Within the SDK, the top-level groupings (`infra`, `modalities`, `runtime`) are
organizational; `core` and `types` stay at the root because nearly everything
depends on them. The Redis stream/pub-sub helpers used by both the runtime and
the service workers live in `infra/realtime/` (a neutral home above `core`),
which is what let the service workers extract cleanly into `agentkit-serve`.